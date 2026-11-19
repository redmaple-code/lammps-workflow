"""Reproducible Fe-Ni-Cr-Co-Cu model-alloy spherical grinding validation."""
from pathlib import Path
import argparse
import json
import shutil
import numpy as np


def prepare(directory, potential, parameters):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    a = parameters['latticeAngstrom']
    nx, ny, nz = parameters['cells']
    basis = np.array([[0, 0, 0], [.5, .5, 0], [.5, 0, .5], [0, .5, .5]])
    cells = np.array(np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing='ij')).reshape(3, -1).T
    positions = ((cells[:, None, :] + basis + .125) * a).reshape(-1, 3)
    rng = np.random.default_rng(parameters['seed'])
    types = np.arange(len(positions)) % 5 + 1
    rng.shuffle(types)
    lx, ly, height = np.array([nx, ny, nz]) * a
    masses = [('Fe', 55.8), ('Ni', 58.69), ('Cr', 52.0), ('Co', 58.93), ('Cu', 63.55)]
    with (directory / 'alloy.data').open('w', encoding='utf-8') as stream:
        stream.write(f'Random equiatomic model FeNiCrCoCu; seed {parameters["seed"]}\n\n')
        stream.write(f'{len(positions)} atoms\n5 atom types\n\n')
        stream.write(f'-12 {lx+12:.10f} xlo xhi\n0 {ly:.10f} ylo yhi\n-5 {height+30:.10f} zlo zhi\n\nMasses\n\n')
        for index, (element, mass) in enumerate(masses, 1):
            stream.write(f'{index} {mass} # {element}\n')
        stream.write('\nAtoms # atomic\n\n')
        for index, (atom_type, position) in enumerate(zip(types, positions), 1):
            stream.write(f'{index} {atom_type} {position[0]:.10f} {position[1]:.10f} {position[2]:.10f}\n')
    shutil.copyfile(potential, directory / 'FeNiCrCoCu-heafixed.setfl')
    r = parameters['radiusAngstrom']
    depth = parameters['depthAngstrom']
    speed = parameters['speedAngstromPerPs']
    temperature = parameters['temperatureK']
    dt = parameters['timeStepPs']
    equil = parameters['equilibrationSteps']
    approach = parameters['approachSteps']
    scratch = parameters['grindingSteps']
    fixed_top = a
    thermostat_top = 3*a
    surface = float(positions[:, 2].max())
    x0, y0 = 5*a, ly/2
    start_z = surface+r+1
    end_z = surface+r-depth
    vz = (end_z-start_z)/(approach*dt)
    script = f'''# Minimal changes from bundled LAMMPS Examples/indent/in.indent.lmp.
# Explicit 3D alloy, frozen boundary, local thermostat, approach and lateral pass.
units metal
dimension 3
boundary f p f
atom_style atomic
read_data alloy.data
pair_style eam/alloy
pair_coeff * * FeNiCrCoCu-heafixed.setfl Fe Ni Cr Co Cu
neighbor 2.0 bin
neigh_modify every 1 delay 0 check yes
region base block INF INF INF INF INF {fixed_top:.8f} units box
group fixed region base
group mobile subtract all fixed
region bath block INF INF INF INF {fixed_top+.00001:.8f} {thermostat_top:.8f} units box
group thermostat region bath
group dynamic subtract mobile thermostat
velocity fixed set 0.0 0.0 0.0
fix freeze fixed setforce 0.0 0.0 0.0
min_style cg
minimize 1.0e-8 1.0e-6 1000 10000
reset_timestep 0
velocity mobile create {temperature} {parameters['seed']} mom yes rot no dist gaussian
fix integrate mobile nve
fix equilibrate mobile langevin {temperature} {temperature} 0.1 {parameters['seed']+13} zero yes
compute Tmobile mobile temp
thermo 100
thermo_style custom step atoms c_Tmobile pe ke etotal
thermo_modify lost error flush yes
timestep {dt}
run {equil}
unfix equilibrate
fix bath thermostat langevin {temperature} {temperature} 0.1 {parameters['seed']+17} zero yes
compute pe all pe/atom
compute coord all coord/atom cutoff 3.2
compute centro all centro/atom fcc
compute cna all cna/atom 3.2
dump trajectory all custom {parameters['dumpEvery']} trajectory.lammpstrj id type x y z c_pe c_coord c_centro c_cna
dump_modify trajectory sort id
write_dump all custom initial.lammpstrj id type x y z modify sort id
variable ztip equal "{start_z:.10f}+(step-{equil})*dt*({vz:.10f})"
fix tool mobile indent {parameters['stiffnessEVPerAngstromCubed']} sphere {x0:.10f} {y0:.10f} v_ztip {r} units box
variable tipx equal {x0:.10f}
variable tipz equal v_ztip
variable tempmobile equal c_Tmobile
variable fx equal f_tool[1]
variable fy equal f_tool[2]
variable fz equal f_tool[3]
fix contact all print {parameters['forceEvery']} "$(step) $(time) $(v_tipx) $(v_tipz) $(v_fx) $(v_fy) $(v_fz) $(v_tempmobile)" file approach.csv screen no title "step time_ps tip_x_A tip_z_A fx_eV_A fy_eV_A fz_eV_A temperature_K"
run {approach}
unfix contact
unfix tool
variable ztip delete
variable xtip equal "{x0:.10f}+(step-{equil+approach})*dt*{speed}"
variable tipx delete
variable tipx equal v_xtip
variable tipz delete
variable tipz equal {end_z:.10f}
fix tool mobile indent {parameters['stiffnessEVPerAngstromCubed']} sphere v_xtip {y0:.10f} {end_z:.10f} {r} units box
fix contact all print {parameters['forceEvery']} "$(step) $(time) $(v_tipx) $(v_tipz) $(v_fx) $(v_fy) $(v_fz) $(v_tempmobile)" file grinding.csv screen no title "step time_ps tip_x_A tip_z_A fx_eV_A fy_eV_A fz_eV_A temperature_K"
run {scratch}
write_dump all custom final.lammpstrj id type x y z c_pe c_coord c_centro c_cna modify sort id
write_data final.data
write_restart final.restart
print "REDMAPLE_GRINDING_COMPLETE"
'''
    (directory / 'in.grinding').write_text(script, encoding='utf-8')
    fixed = positions[:, 2] <= fixed_top
    report = dict(atomCount=len(positions), counts={element: int(np.sum(types == i)) for i, (element, _) in enumerate(masses, 1)},
                  boxAngstrom=[lx, ly, height], surfaceAngstrom=surface, fixedAtomCount=int(fixed.sum()),
                  mobileAtomCount=int((~fixed).sum()), nearestNeighborAngstrom=a/np.sqrt(2),
                  verifiedFeatures=['five-components', 'fcc-substrate', 'fixed-boundary', 'thermal-layer', 'spherical-abrasive', 'lateral-motion'],
                  parameters=parameters, massMapping=[dict(element=e, mass=m) for e, m in masses])
    (directory / 'structure-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def read_dump(path):
    with Path(path).open() as stream:
        assert stream.readline().strip() == 'ITEM: TIMESTEP'
        step = int(stream.readline())
        assert stream.readline().strip() == 'ITEM: NUMBER OF ATOMS'
        count = int(stream.readline())
        stream.readline()
        bounds = [list(map(float, stream.readline().split())) for _ in range(3)]
        columns = stream.readline().split()[2:]
        data = np.array([list(map(float, stream.readline().split())) for _ in range(count)])
    order = np.argsort(data[:, columns.index('id')])
    return step, columns, data[order], bounds


def analyze(directory):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    directory = Path(directory)
    report = json.loads((directory/'structure-report.json').read_text())
    data = np.loadtxt(directory/'grinding.csv', skiprows=1)
    _, initial_columns, initial, _ = read_dump(directory/'initial.lammpstrj')
    _, columns, final, _ = read_dump(directory/'final.lammpstrj')
    p0 = initial[:, [initial_columns.index(c) for c in ['x', 'y', 'z']]]
    p1 = final[:, [columns.index(c) for c in ['x', 'y', 'z']]]
    displacement = p1 - p0
    ly = report['boxAngstrom'][1]
    displacement[:, 1] -= np.rint(displacement[:, 1]/ly)*ly
    fixed = p0[:, 2] <= report['parameters']['latticeAngstrom']
    fixed_displacement = float(np.linalg.norm(displacement[fixed], axis=1).max())
    magnitude = np.linalg.norm(displacement, axis=1)
    forces = data[:, 4:7]*1.602176634
    tail = forces[len(forces)//2:]
    figures = directory/'figures'
    figures.mkdir(exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    axes[0].plot(data[:, 2]/10, -forces[:, 0], label='Tangential reaction magnitude/sign (-Fx)')
    axes[0].plot(data[:, 2]/10, forces[:, 2], label='Normal reaction Fz')
    axes[0].set_ylabel('Force (nN)'); axes[0].legend(fontsize=8)
    axes[1].plot(data[:, 2]/10, data[:, 7], color='#c15b32')
    axes[1].set_ylabel('Mobile temperature (K)'); axes[1].set_xlabel('Abrasive center x (nm)')
    fig.tight_layout(); fig.savefig(figures/'force-temperature.png', dpi=160); plt.close(fig)
    selection = np.abs(p0[:, 1]-ly/2) < 5
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), sharex=True, sharey=True, layout='constrained')
    axes[0].scatter(p0[selection, 0]/10, p0[selection, 2]/10, s=2, c='#3c6778')
    image = axes[1].scatter(p1[selection, 0]/10, p1[selection, 2]/10, s=2, c=magnitude[selection]/10, cmap='inferno', vmin=0, vmax=max(.1,float(magnitude[selection].max()/10)))
    for ax, title in zip(axes, ['Before contact', 'After grinding pass']):
        ax.set_title(title); ax.set_xlabel('x (nm)'); ax.set_aspect('equal')
    axes[0].set_ylabel('z (nm)'); fig.colorbar(image, ax=axes, label='Displacement (nm)', shrink=.85)
    fig.savefig(figures/'cross-section.png', dpi=160); plt.close(fig)
    finite = bool(np.isfinite(data).all() and np.isfinite(final).all())
    contact_samples = int(np.sum(np.linalg.norm(forces, axis=1)>1e-5))
    metrics = dict(atomCount=len(final), initialAtomCount=len(initial), sampleCount=len(data),
                   fixedMaxDisplacementAngstrom=fixed_displacement, finite=finite, contactSamples=contact_samples,
                   tipTravelAngstrom=float(data[-1, 2]-data[0, 2]),
                   meanTangentialForceNn=float((-tail[:,0]).mean()), meanNormalForceNn=float(tail[:,2].mean()),
                   peakNormalForceNn=float(forces[:,2].max()), meanTemperatureK=float(data[:,7].mean()),
                   maxDisplacementAngstrom=float(magnitude.max()), displacedAtomsAboveOneAngstrom=int(np.sum(magnitude>1)),
                   method='grinding-force-temperature-displacement/1',
                   window=dict(stepStart=float(data[0,0]),stepEnd=float(data[-1,0]),forceAveraging='second half of grinding pass'),
                   limitations=['Farkas-Caro idealized FCC model alloy', 'Repulsive spherical tool without explicit abrasive atoms or chemistry',
                                'Small cell and short MD time, single seed, no convergence or experimental grinding validation'])
    (directory/'analysis.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    return metrics


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare','analyze'])
    parser.add_argument('--directory', required=True)
    parser.add_argument('--potential')
    parser.add_argument('--parameters')
    args = parser.parse_args()
    result = prepare(args.directory, args.potential, json.loads(Path(args.parameters).read_text())) if args.action == 'prepare' else analyze(args.directory)
    print(json.dumps(result))
