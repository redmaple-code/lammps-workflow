import { readFile } from 'node:fs/promises';

export function parseCommands(text) {
  return text.replace(/&\s*\r?\n/g, ' ').split(/\r?\n/).map((line, index) => ({
    line: index + 1, text: line.replace(/#.*/, '').trim() })).filter(item => item.text);
}
const check = (checkId, applicability, passed, observations, action = 'blocked') => ({ checkId, applicability,
  result: applicability === false ? 'notApplicable' : applicability === 'unknown' ? 'insufficient' : passed ? 'passed' : 'failed', observations, action });

export function checkLammpsInput(text, { mapping, potentialElements, masses, features, structureReport, requiredOutputs = [], restartSource } = {}) {
  const commands = parseCommands(text);
  const has = pattern => commands.some(command => pattern.test(command.text));
  const lines = pattern => commands.filter(command => pattern.test(command.text)).map(command => `line ${command.line}: ${command.text}`);
  const result = [];
  const deform = has(/^fix\s+\S+\s+\S+\s+deform\b/);
  result.push(check('MB-001', deform, !deform || (has(/^variable\s+L0\s+equal\s+\$\{/) && !has(/^variable\s+strain\s+equal.*\b(lx|ly|lz)\b/)),
    deform ? lines(/L0|strain|deform/) : ['No fix deform commands in this input']));
  const fixed = has(/^group\s+(fixed|frozen|lower)\b/);
  result.push(check('MB-002', fixed && has(/^velocity\b/), !has(/^velocity\s+all\s+create/) && has(/^velocity\s+mobile\s+create/)
    && has(/^group\s+mobile\s+subtract\s+all\s+fixed/), fixed ? lines(/^group|^velocity/) : ['No constrained atom group']));
  const npt = commands.filter(command => /^fix\s+\S+\s+\S+\s+npt\b/.test(command.text));
  let competing = false;
  for (const command of commands.filter(command => /^fix\s+\S+\s+\S+\s+deform\b/.test(command.text))) {
    for (const axis of ['x', 'y', 'z']) if (new RegExp(`\\b${axis}\\s+(erate|trate|final|delta|scale|vel|wiggle)`).test(command.text)) {
      competing ||= npt.some(item => new RegExp(`\\b${axis}\\s+[-.\\d]|\\b(iso|aniso|tri)\\s`).test(item.text));
    }
  }
  result.push(check('MB-003', deform && npt.length > 0, !competing, deform && npt.length ? lines(/npt|deform/) : ['NPT and deform are not simultaneously present']));
  const reactive = has(/^pair_style.*reax/);
  result.push(check('MB-004', reactive, has(/^atom_style\s+(charge|full)$/) && has(/^fix\s+\S+\s+\S+\s+qeq\/(reaxff|shielded|reax)\b/),
    reactive ? lines(/reax|atom_style|qeq/) : ['No ReaxFF pair style']));
  const prints = commands.filter(command => /^fix\s+\S+\s+\S+\s+print\b/.test(command.text));
  result.push(check('MB-005', prints.length > 0, prints.every(command => {
    const withoutImmediateExpressions = command.text.replace(/\$\([^)]*\)/g, '');
    return !/"[^"\n]*\bv_[a-zA-Z]\w*[^"\n]*"/.test(withoutImmediateExpressions) && !/\$\{/.test(withoutImmediateExpressions);
  }), prints.length ? prints.map(item => `line ${item.line}: ${item.text}`) : ['No fix print commands']));
  const pair = commands.filter(command => /^pair_coeff\b/.test(command.text));
  let mappingPassed = !!mapping && !!potentialElements && !!masses;
  if (mappingPassed) mappingPassed = mapping.length === masses.length && mapping.every((element, index) =>
    potentialElements.includes(element) && masses[index].element === element && masses[index].mass > 0);
  for (const command of pair) if (/\.setfl|eam\.alloy/.test(command.text) && mapping) {
    mappingPassed &&= command.text.trim().split(/\s+/).slice(-mapping.length).join(' ') === mapping.join(' ');
  }
  result.push(check('MB-006', pair.length > 0, mappingPassed, pair.length ? [...pair.map(item => `line ${item.line}: ${item.text}`), `Mapping verification ${JSON.stringify({ mapping, potentialElements, masses })}`] : ['No pair_coeff commands']));
  const restart = has(/^read_restart\b/) || !!restartSource;
  result.push(check('MB-007', restart, !!restartSource?.origin && !!restartSource?.createdAt && restartSource?.boxVerified === true,
    restart ? [JSON.stringify(restartSource || { missing: 'restart provenance' })] : ['read_data builds a new model with source metadata, no continuation requested']));
  const featureKnown = features?.length > 0 && features.some(feature => feature.criticality === 'critical');
  const featuresPresent = featureKnown && features.filter(feature => feature.criticality === 'critical').every(feature => structureReport?.verifiedFeatures?.includes(feature.id));
  result.push(check('MB-008', true, featuresPresent, [JSON.stringify({ features: features || [], verified: structureReport?.verifiedFeatures || [] })]));
  const diagnostic = ['pe/atom', 'coord/atom', 'centro/atom', 'cna/atom'];
  const diagnosticPassed = diagnostic.every(style => commands.some(command => command.text.startsWith('compute ') && command.text.includes(style)))
    && has(/^dump\s+.*c_pe.*c_coord.*c_centro.*c_cna/);
  result.push(check('MB-009', true, diagnosticPassed, lines(/^compute|^dump/)));
  const missing = requiredOutputs.filter(output => !text.includes(output));
  result.push(check('OUTPUT-CLOSURE', true, missing.length === 0, [`Required output references ${JSON.stringify(requiredOutputs)}, missing ${JSON.stringify(missing)}`], 'revise'));
  if (has(/^(include|jump)\b/)) return result.map(item => ({ ...item, applicability: 'unknown', result: 'insufficient',
    observations: [...item.observations, 'Expand include/jump dependencies and review the resulting command closure'] }));
  return result;
}

export async function potentialMetadata(path) {
  const lines = (await readFile(path, 'utf8')).split(/\r?\n/);
  const elements = lines[3].trim().split(/\s+/).slice(1);
  return { elements, cutoff: Number(lines[4].trim().split(/\s+/)[4]), header: lines.slice(0, 6) };
}

export function inspectStructureData(text, { latticeAngstrom, inputText = '' }) {
  const atomSection = text.split(/\nAtoms[^\n]*\r?\n/)[1];
  if (!atomSection) return { passed: false, verifiedFeatures: [], reasons: ['Missing atomic data section'] };
  const atoms = atomSection.trim().split(/\r?\n/).map(line => line.trim().split(/\s+/).slice(0, 5).map(Number));
  const declared = Number(text.match(/(\d+) atoms/)?.[1]);
  const counts = Array(5).fill(0), unique = new Set();
  let fcc = true, finite = true, fixed = 0, mobile = 0;
  for (const [atomId, type, x, y, z] of atoms) {
    finite &&= [atomId, type, x, y, z].every(Number.isFinite) && type >= 1 && type <= 5;
    counts[type - 1] += 1;
    const coordinates = [x, y, z].map(value => (value / latticeAngstrom - .125) * 2);
    const integers = coordinates.map(Math.round);
    fcc &&= coordinates.every((value, i) => Math.abs(value - integers[i]) < 1e-6) && integers.reduce((a, b) => a + b, 0) % 2 === 0;
    unique.add(`${x},${y},${z}`);
    if (z <= latticeAngstrom) fixed++; else mobile++;
  }
  const verifiedFeatures = [];
  if (counts.every(count => count > 0)) verifiedFeatures.push('five-components');
  if (fcc && unique.size === atoms.length) verifiedFeatures.push('fcc-substrate');
  if (fixed > 0 && mobile > 0) verifiedFeatures.push('fixed-boundary');
  if (/group\s+thermostat\s+region/.test(inputText) && /fix\s+bath\s+thermostat\s+langevin/.test(inputText)) verifiedFeatures.push('thermal-layer');
  if (/fix\s+tool\s+mobile\s+indent\s+\S+\s+sphere/.test(inputText)) verifiedFeatures.push('spherical-abrasive');
  if (/variable\s+xtip\s+equal.*step.*dt/.test(inputText) && /sphere\s+v_xtip/.test(inputText)) verifiedFeatures.push('lateral-motion');
  return { passed: finite && declared === atoms.length && unique.size === atoms.length && fcc, atomCount: atoms.length,
    counts, fixedAtomCount: fixed, mobileAtomCount: mobile, verifiedFeatures, method: 'independent-raw-data-fcc-inspection/1' };
}
