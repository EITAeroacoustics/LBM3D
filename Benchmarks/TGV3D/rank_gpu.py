"""Select one GPU per local MPI rank before the solver calls MPI_Init."""

import os
import sys


devices = os.environ["LBM_GPU_MAP"].split(",")
rank = int(os.environ["OMPI_COMM_WORLD_LOCAL_RANK"])
os.environ["CUDA_VISIBLE_DEVICES"] = devices[rank]
os.execv(sys.argv[1], sys.argv[1:])
