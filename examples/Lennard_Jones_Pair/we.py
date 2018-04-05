"""Very simple example using a pair of Lennard-Jones particles.

Requires the package `openmmtools` which can be installed from
anaconda: `conda install -c omnia openmmtools`

Openmmtools just provides a ready-made system for the lennard jones
particles.

This script is broken up into several parts:

1. Importing the pieces from wepy to run a WExplore simulation.

2. Definition of a distance metric for this system and process.

3. Definition of the parameters used in the simulation. Each is
described in detail.

4. Definition of the I/O end points.

5. Initialize the OpenMM Runner and get the starting state from the
openmmtools system.

6. Initialize the Wexplore resampler.

7. Initialize the boundary conditions. This makes the simulation
non-equilibrium by restarting "unbound" simulations in the initial
state.

8. Initialize the reporters. This will result in the results files.

9. Initialize the work mapper, which in this case is trivial since
this will only be run in serial.

10. Initialize the simulation manager with all the parts.

11. Actually run the simulation.

"""

import sys
from copy import copy
import os
import os.path as osp

import numpy as np

import simtk.openmm.app as omma
import simtk.openmm as omm
import simtk.unit as unit

from openmmtools.testsystems import LennardJonesPair
import mdtraj as mdj
from wepy.util.mdtraj import mdtraj_to_json_topology

from wepy.sim_manager import Manager

from wepy.resampling.distances.distance import Distance
from wepy.resampling.wexplore1 import WExplore1Resampler
from wepy.walker import Walker
from wepy.runners.openmm import OpenMMRunner, OpenMMState
from wepy.runners.openmm import UNIT_NAMES, GET_STATE_KWARG_DEFAULTS
from wepy.work_mapper.mapper import Mapper
from wepy.boundary_conditions.unbinding import UnbindingBC
from wepy.reporter.hdf5 import WepyHDF5Reporter

from scipy.spatial.distance import euclidean


## PARAMETERS

# Platform used for OpenMM which uses different hardware computation
# kernels. Options are: Reference, CPU, OpenCL, CUDA.

# we use the Reference platform because this is just a test
PLATFORM = 'Reference'

# Langevin Integrator
TEMPERATURE= 300.0*unit.kelvin
FRICTION_COEFFICIENT = 1/unit.picosecond
# step size of time integrations
STEP_SIZE = 0.002*unit.picoseconds

# Resampler parameters

# the maximum weight allowed for a walker
PMAX = 0.5
# the minimum weight allowed for a walker
PMIN = 1e-12

# the maximum number of regions allowed under each parent region
MAX_N_REGIONS = (10, 10, 10, 10)

# the maximum size of regions, new regions will be created if a walker
# is beyond this distance from each voronoi image unless there is an
# already maximal number of regions
MAX_REGION_SIZES = (1, 0.5, .35, .25) # nanometers

# boundary condition parameters

# maximum distance between between any atom of the ligand and any
# other atom of the protein, if the shortest such atom-atom distance
# is larger than this the ligand will be considered unbound and
# restarted in the initial state
CUTOFF_DISTANCE = 1.0 # nm

# reporting parameters

# these are the properties of the states (i.e. from OpenMM) which will
# be saved into the HDF5
SAVE_FIELDS = ('positions', 'box_vectors', 'velocities')
# these are the names of the units which will be stored with each
# field in the HDF5
UNITS = UNIT_NAMES

## INPUTS/OUTPUTS

# the inputs directory
inputs_dir = osp.realpath('./inputs')
# the outputs path
outputs_dir = osp.realpath('./outputs')
# make the outputs dir if it doesn't exist
os.makedirs(outputs_dir, exist_ok=True)

# inputs filenames
json_top_filename = "pair.top.json"

# outputs
hdf5_filename = 'results.wepy.h5'

# normalize the input paths
json_top_path = osp.join(inputs_dir, json_top_filename)

# normalize the output paths
hdf5_path = osp.join(outputs_dir, hdf5_filename)

## System and OpenMMRunner

# make the test system from openmmtools
test_sys = LennardJonesPair()

# make the integrator
integrator = omm.LangevinIntegrator(TEMPERATURE, FRICTION_COEFFICIENT, STEP_SIZE)

# make a context and set the positions
context = omm.Context(test_sys.system, copy(integrator))
context.setPositions(test_sys.positions)

# get the data from this context so we have a state to start the
# simulation with
get_state_kwargs = dict(GET_STATE_KWARG_DEFAULTS)
init_sim_state = context.getState(**get_state_kwargs)
init_state = OpenMMState(init_sim_state)

# initialize the runner
runner = OpenMMRunner(test_sys.system, test_sys.topology, integrator, platform=PLATFORM)

## Distance Metric
# we define a simple distance metric for this system, assuming the
# positions are in a 'positions' field
class PairDistance(Distance):

    def __init__(self, metric=euclidean):
        self.metric = metric

    def image(self, state):
        return state['positions']

    def image_distance(self, image_a, image_b):
        dist_a = self.metric(image_a[0], image_a[1])
        dist_b = self.metric(image_b[0], image_b[1])

        return np.abs(dist_a - dist_b)


# make a distance object which can be used to compute the distance
# between two walkers, for our scorer class
distance = PairDistance()

## Resampler
resampler = WExplore1Resampler(distance=distance,
                               init_state=init_state,
                               max_region_sizes=MAX_REGION_SIZES,
                               max_n_regions=MAX_N_REGIONS,
                               pmin=PMIN, pmax=PMAX)

## Boundary Conditions

# the mdtraj here is needed for the distance function
mdtraj_topology = mdj.Topology.from_openmm(test_sys.topology)

# initialize the unbinding boundary conditions
ubc = UnbindingBC(cutoff_distance=CUTOFF_DISTANCE,
                  initial_state=init_state,
                  topology=mdtraj_topology,
                  ligand_idxs=np.array(test_sys.ligand_indices),
                  binding_site_idxs=np.array(test_sys.receptor_indices))

## Reporters

json_str_top = mdtraj_to_json_topology(mdtraj_topology)
# make a dictionary of units for adding to the HDF5
units = dict(UNIT_NAMES)

# open it in truncate mode first, then switch after first run
hdf5_reporter = WepyHDF5Reporter(hdf5_path, mode='w',
                                 save_fields=SAVE_FIELDS,
                                 resampler=resampler,
                                 boundary_conditions=ubc,
                                 topology=json_str_top,
                                 units=units,
)


## Work Mapper

# a simple work mapper
mapper = Mapper()



## Run the simulation


if __name__ == "__main__":

    if sys.argv[1] == "-h" or sys.argv[1] == "--help":
        print("arguments: n_runs, n_cycles, n_steps, n_walkers")
    else:
        n_runs = int(sys.argv[1])
        n_cycles = int(sys.argv[2])
        n_steps = int(sys.argv[3])
        n_walkers = int(sys.argv[4])

        print("Number of steps: {}".format(n_steps))
        print("Number of cycles: {}".format(n_cycles))

        # create the initial walkers
        init_weight = 1.0 / n_walkers
        init_walkers = [Walker(OpenMMState(init_sim_state), init_weight) for i in range(n_walkers)]

        # initialize the simulation manager
        sim_manager = Manager(init_walkers,
                              runner=runner,
                              resampler=resampler,
                              boundary_conditions=ubc,
                              work_mapper=mapper,
                              reporters=[hdf5_reporter])

        # make a number of steps for each cycle. In principle it could be
        # different each cycle
        steps = [n_steps for i in range(n_cycles)]

        # actually run the simulations
        print("Running Simulations")
        for run_idx in range(n_runs):
            print("Starting run: {}".format(run_idx))
            sim_manager.run_simulation(n_cycles, steps, debug_prints=True)
            print("Finished run: {}".format(run_idx))


        print("Finished first file")
