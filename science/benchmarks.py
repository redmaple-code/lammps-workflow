"""Real plane-stress finite-element and discrete-event reference calculations."""
import argparse
import json
from pathlib import Path
import warnings
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve, MatrixRankWarning
from scipy.stats import t


def beam(nx, ny, constrained=True):
    if not constrained:
        raise ValueError('Missing essential displacement boundary conditions')
    length, height, thickness, young, nu, load = 1., .1, .01, 210e9, .3, -1000.
    coordinates = np.array([(x, y) for x in np.linspace(0, length, nx+1) for y in np.linspace(0, height, ny+1)])
    elements = []
    for i in range(nx):
        for j in range(ny):
            a=i*(ny+1)+j; b=a+ny+1
            elements += [(a,b,b+1),(a,b+1,a+1)]
    constitutive = young/(1-nu**2)*np.array([[1,nu,0],[nu,1,0],[0,0,(1-nu)/2]])
    rows, cols, vals = [], [], []
    for element in elements:
        points=coordinates[list(element)]
        area=abs(np.linalg.det(np.column_stack([np.ones(3), points])))/2
        b=np.roll(points[:,1],-1)-np.roll(points[:,1],-2)
        c=np.roll(points[:,0],-2)-np.roll(points[:,0],-1)
        strain=np.zeros((3,6))
        strain[0,0::2]=b; strain[1,1::2]=c; strain[2,0::2]=c; strain[2,1::2]=b
        strain/=2*area
        stiffness=thickness*area*strain.T@constitutive@strain
        indices=np.array([[2*n,2*n+1] for n in element]).ravel()
        for k,row in enumerate(indices):
            for m,col in enumerate(indices):
                rows.append(row);cols.append(col);vals.append(stiffness[k,m])
    ndof=len(coordinates)*2
    stiffness=coo_matrix((vals,(rows,cols)),shape=(ndof,ndof)).tocsr()
    force=np.zeros(ndof)
    right=np.flatnonzero(np.isclose(coordinates[:,0],length))
    force[2*right+1]=load/ny
    force[2*right[[0,-1]]+1]*=.5
    fixed_nodes=np.flatnonzero(np.isclose(coordinates[:,0],0))
    fixed=np.array([[2*n,2*n+1] for n in fixed_nodes]).ravel()
    free=np.setdiff1d(np.arange(ndof),fixed)
    displacement=np.zeros(ndof)
    with warnings.catch_warnings():
        warnings.simplefilter('error',MatrixRankWarning)
        displacement[free]=spsolve(stiffness[free][:,free],force[free])
    reaction=stiffness@displacement-force
    tip=float(displacement[2*right+1].mean())
    reference=load*length**3/(3*young*(thickness*height**3/12))
    return dict(nx=nx,ny=ny,nodes=len(coordinates),elements=len(elements),tipDisplacementM=tip,
                eulerBernoulliReferenceM=reference,relativeDifference=abs(tip-reference)/abs(reference),
                forceBalanceRelative=abs(reaction[2*fixed_nodes+1].sum()+load)/abs(load),
                coordinates=coordinates.tolist(),displacement=displacement.reshape(-1,2).tolist())


def queue(arrival_rate=0.8, service_rate=1., count=50000, warmup=2000, repeats=12):
    if arrival_rate>=service_rate:
        raise ValueError('lambda >= mu has no stationary M/M/1 waiting-time target')
    means=[]
    for seed in range(repeats):
        rng=np.random.default_rng(6800+seed)
        arrival=np.cumsum(rng.exponential(1/arrival_rate,count+warmup))
        service=rng.exponential(1/service_rate,count+warmup)
        departure=np.empty(len(arrival))
        previous=0.
        for i in range(len(arrival)):
            departure[i]=max(arrival[i],previous)+service[i]
            previous=departure[i]
        wait=departure-arrival-service
        means.append(float(wait[warmup:].mean()))
    mean=float(np.mean(means))
    error=float(t.ppf(.975,repeats-1)*np.std(means,ddof=1)/np.sqrt(repeats))
    theoretical=arrival_rate/(service_rate*(service_rate-arrival_rate))
    return dict(arrivalRatePerSecond=arrival_rate,serviceRatePerSecond=service_rate,eventsPerReplication=count,
                warmupEvents=warmup,replications=repeats,seeds=list(range(6800,6800+repeats)),
                meanQueueWaitingSeconds=mean,confidenceInterval95=[mean-error,mean+error],
                theoreticalQueueWaitingSeconds=theoretical,theoreticalSystemTimeSeconds=1/(service_rate-arrival_rate),
                replicationMeans=means,relativeError=abs(mean-theoretical)/theoretical)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',required=True)
    args=parser.parse_args()
    target=Path(args.directory);target.mkdir(parents=True,exist_ok=True)
    meshes=[beam(24,4),beam(48,8),beam(96,16)]
    for mesh in meshes:
        (target/f'beam-{mesh["nx"]}.json').write_text(json.dumps(mesh),encoding='utf-8')
    event=queue()
    (target/'queue.json').write_text(json.dumps(event,indent=2),encoding='utf-8')
    negatives={}
    for name,fn in [('unconstrained',lambda:beam(4,2,False)),('nonstationary',lambda:queue(1.2,1.))]:
        try:fn();negatives[name]='unexpectedSuccess'
        except ValueError as error:negatives[name]=str(error)
    summary=dict(beam=[{k:v for k,v in mesh.items() if k not in ['coordinates','displacement']} for mesh in meshes],queue=event,
                 negativeCases=negatives,method='plane-stress-CST-and-MM1-event-loop/1',
                 modelValidation='Reference problems only. Experimental model validation has not been performed.')
    (target/'benchmark-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary))
