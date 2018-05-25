from sklearn.neighbors import NearestNeighbors
from scipy.spatial import distance
import numpy as np
import os
from copy import deepcopy
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.collections  as mc
from scipy.io import savemat
from sklearn.metrics.pairwise import pairwise_distances
from ripser_interface import ripser
from supVR import compute_C_first, update_P, init_C_inds, compute_C_closest
from logging import warn
from time import time
from common_utils import create_dir_if_not_exist
from exceptions import ValueError

class TopologicalData:

    def __init__(self, x, y, graphtype, scale, k = None, showComplexes = False,
                 saveComplexes = True, use_cy = False, N = None, exptid = "0",
                 PH_program = "ripser", maxdim = 1, njobs = 28, 
                 dipha_path = "../dipha/build/dipha",
                 ripser_path = '../ripser/ripser'):
        """
        dims - 0 (simply connected components), 1 (1-dimensional holes)
        """
        
        assert(graphtype)
        
        self.graphtype = graphtype
        self.scale = scale
        self.maxdim = maxdim
        self.dims = None
        self.birth_values = None
        self.death_values = None
        self.showComplexes = showComplexes
        self.saveComplexes = saveComplexes
        self.exptid = exptid
        self.PH_program = PH_program
        self.njobs = njobs
        self.dipha_path = dipha_path
        self.ripser_path = ripser_path
        self.bc = None

        # Intermediate files dir
        create_dir_if_not_exist("intermediate")

        # results dir
        create_dir_if_not_exist("results")
        create_dir_if_not_exist(os.path.join("results", 
                                "expt_"+str(self.exptid)))
        
        if graphtype == "beta":
            self.ngl_exec = "../ngl/src/compute-neighborhood"
            self.P, self.nTriv, self.numFilt =\
                self.beta_opposing_simplex(x, y, scale)
            self.beta = scale
        elif graphtype == "knn":
            if not use_cy:
                self.P, self.nTriv, self.numFilt =\
                    self.localscale_neighbors_opposing(x, y, scale)
            else:
                if N is None:
                    warn("N is not specified, defaulting to 1/10 of number of examples")
                    N = int(x.shape[0]*0.1)
                else:
                    N = np.minimum(N, x.shape[0])

                self.P, self.nTriv, self.numFilt =\
                    self.localscale_neighbors_opposing_x(x, y, scale, N)

        elif graphtype == "knn_rho":
            assert(k)
            if not use_cy:
                self.P, self.nTriv, self.numFilt =\
                    self.localscale_neighbors_opposing_r(x, y, k, scale)
            else:
                if N is None:
                    warn("N is not specified, defaulting to 1/10 of number of examples")
                    N = int(x.shape[0]*0.1)
                else:
                    N = np.minimum(N, x.shape[0])

                self.P, self.nTriv, self.numFilt, self.C =\
                    self.localscale_neighbors_opposing_r_x(x, y, k, N, scale)  

        elif graphtype == "eps":
            assert(k)
            if not use_cy:
                self.P, self.nTriv, self.numFilt =\
                    self.epsilon_neighbors_opposing(x, y, k, scale)
            else:
                if N is None:
                    warn("N is not specified, defaulting to 1/10 of number of examples")
                    N = int(x.shape[0]*0.1)
                else:
                    N = np.minimum(N, x.shape[0])

                self.P, self.nTriv, self.numFilt, self.C =\
                    self.epsilon_neighbors_opposing_x(x, y, k, N, scale) 

    def localscale_neighbors_opposing(self, x, y, neighborsv):
        
        """ 
        k nearest neighbors from opposing classes 
        (class other than that of the example considered)

        x - data points
        y - class membership
        neighborsv - nearest neighbors to be considered from opposing class for 
                     computing local scale

        2 hop neighbors are then computed to complete the triangles and form
        simplices
        """
    
        P = np.zeros((x.shape[0], x.shape[0]), dtype = np.int)
        numFilt = len(neighborsv)
        nTriv = np.zeros(numFilt)

        rows = np.ceil(float(numFilt)/5)
        cols = 5

        C = np.zeros(P.shape)
        C1 = np.zeros(P.shape)
        C1bool = np.zeros(P.shape, dtype = np.bool)

        # Mask specifying Trues for blocks where row and column have
        # same labels
        mask_mat = np.add(*[np.outer((y == uy), (y == uy))
                        for uy in np.unique(y)])

        for j, k in enumerate(neighborsv):

            B, D = self.k_neighbors_opposing(x, y, k)

            # Sigma array
            sigarr = np.reshape(np.max(np.multiply(D, B), axis = 1), (-1,1))
            sigmat = np.dot(np.sqrt(sigarr), np.sqrt(sigarr.T))

            # Neighbors with local scale
            #C = (D <= sigmat).astype(float)
            np.less_equal(D, sigmat, out = C)

            C[mask_mat] = 0.0
            # for i in range(x.shape[0]):
            #     same_inds = (y == y[i])
            #     C[i, same_inds] = 0.0
            #     C[same_inds, i] = 0.0

            # Set diagonals to 1
            np.fill_diagonal(C, 1.0)
            np.dot(C, C.transpose(), out = C1)
            # C = np.double(np.dot(C, C) > 0)

            np.greater(C1, 0.0, out = C1bool)
            np.add(P,1, out = P, where = C1bool)
            # P = P + C
            
            nTriv[j] = sum(np.sum(C, axis = 0) == 1)

            if self.showComplexes:
                f = plt.figure(num = 1000, figsize = (rows*5, cols*5))
                titl = "k = " + str(neighborsv[j])
                self.show_simplicial_complex(x, y, C1bool.astype(np.double),
                                             f, rows, cols, j+1, titl)

            if self.saveComplexes:
                titl = "r = " + str(neighborsv[j])
                self.save_simplicial_complex(x, y, C1bool.astype(np.double),
                                             rows, cols, j+1, titl)
                                
        P = numFilt - P

        return P, nTriv, numFilt

    def localscale_neighbors_opposing_x(self, x, y, neighborsv, N):
        
        """ 
        k nearest neighbors from opposing classes 
        (class other than that of the example considered)

        x - data points
        y - class membership
        neighborsv - nearest neighbors to be considered from opposing class for 
                     computing local scale
        N - max number of nearest neighbors from opposing classes (user parameter)

        2 hop neighbors are then computed to complete the triangles and form
        simplices
        SIMILAR to localscale_neighbors_opposing but uses Cython for speedup
        This involves restricting the maximum number of neighbors for each point to N
        """
    
        numFilt = len(neighborsv)
        nTriv = np.zeros(numFilt)
        m = x.shape[0]

        rows = np.ceil(float(numFilt)/5)
        cols = 5

        # Adjust N depending on max(neighborsv)
        N = int(np.maximum(N, np.max(neighborsv)))
        print("N adjusted to %d based on requested max nearest neighbors" % (N))

        # Compute opposing neighbors
        S, DN = self.opposing_neighbors(x, y, N)

        # Other inits
        C = -1*np.ones((m,N+1), dtype = np.int32)
        Pupd = np.zeros((m,m), dtype = np.int32)
        P = np.zeros((m,m), dtype = np.int32)
        inds = np.zeros(m, dtype = np.int32)

        for j, k in enumerate(neighborsv):
            # Sigma array
            sigarr = np.sqrt(DN[:,int(k)-1].ravel())

            # Re-initialize some arrays
            if j > 0:
                C.fill(-1)
                inds.fill(0)
                Pupd.fill(0)

            # Call Cython functions for updating P
            init_C_inds(C, inds)
            compute_C_closest(C, S, inds, DN, 1.0, sigarr)
            update_P(C, inds, Pupd, 1)
            np.maximum(Pupd, Pupd.transpose(), out = Pupd)
            np.add(P, Pupd, out = P)            

            nTriv[j] = np.sum(inds == 1)

            if self.showComplexes:
                f = plt.figure(num = 1000, figsize = (rows*5, cols*5))
                titl = "k = " + str(neighborsv[j])
                self.show_simplicial_complex(x, y, Pupd.astype(np.double),
                                             f, rows, cols, j+1, titl)

            if self.saveComplexes:
                titl = "r = " + str(neighborsv[j])
                self.save_simplicial_complex(x, y, Pupd.astype(np.double),
                                             rows, cols, j+1, titl)


        P = numFilt - P

        return P, nTriv, numFilt

    def epsilon_neighbors_opposing(self, x, y, k, rho):
        
        """ 
        epsilon nearest neighbors from opposing classes 
        (class other than that of the example considered)

        x - data points
        y - class membership
        k - nearest neighbors to be considered from opposing class for 
            computing local scale
        rho - list of epsilons to be used when computing the graph. 
            For a value r from this, an edge will be created when
            d(x_i, x_j) < r and i, j belong to
            opposing classes
        
        2 hop neighbors are then computed to complete the triangles and form
        simplices
        """
    
        numFilt = len(rho)
        nTriv = np.zeros(numFilt)

        rows = np.ceil(float(numFilt)/5)
        cols = 5
        
        D = pairwise_distances(x, metric="euclidean", n_jobs=self.njobs)

        # Sigma array
        sigmat = np.ones(np.shape(D))
        
        C = np.zeros(D.shape)
        C1 = np.zeros(D.shape)
        C1bool = np.zeros(D.shape, dtype = np.bool)
        P = np.zeros(D.shape, dtype = np.int)

        # Mask specifying Trues for blocks where row and column have
        # same labels
        mask_mat = np.add(*[np.outer((y == uy), (y == uy))
                        for uy in np.unique(y)])

        for j, r in enumerate(rho):

            # Neighbors with local scale
            np.less_equal(D, r * sigmat, out = C)

            C[mask_mat] = 0.0

            # for i in range(x.shape[0]):
            #     same_inds = (y == y[i])
            #     C[i, same_inds] = 0.0
            #     C[same_inds, i] = 0.0

            # Set diagonals to 1
            np.fill_diagonal(C, 1.0)
            # np.dot(C, C, out = C1)
            np.dot(C, C.transpose(), out = C1)

            np.greater(C1, 0.0, out = C1bool)
            np.add(P,1, out = P, where = C1bool)

            nTriv[j] = sum(np.sum(C, axis = 0) == 1)

            if self.showComplexes:
                f = plt.figure(num = 1000, figsize = (rows*5, cols*5))
                titl = "r = " + str(r)
                self.show_simplicial_complex(x, y, C1bool.astype(np.double),
                                            f, rows, cols, j+1, titl)

            if self.saveComplexes:
                titl = "r = " + str(r)
                self.save_simplicial_complex(x, y, C1bool.astype(np.double),
                                             rows, cols, j+1, titl)

        P = numFilt - P

        return P, nTriv, numFilt 
    
    def epsilon_neighbors_opposing_x(self, x, y, k, N, rho):
        
        """ 
        epsilon nearest neighbors from opposing classes 
        (class other than that of the example considered)

        x - data points
        y - class membership
        k - nearest neighbors to be considered from opposing class for 
            computing local scale
        rho - list of epsilons to be used when computing the graph. 
            For a value r from this, an edge will be created when
            d(x_i, x_j) < r and i, j belong to
            opposing classes
        
        2 hop neighbors are then computed to complete the triangles and form
        simplices

        SIMILAR to epsilon_neighbors_opposing but uses Cython for speedup
        This involves restricting the maximum number of neighbors for each point to N
        """
    
        numFilt = len(rho)
        nTriv = np.zeros(numFilt)
        m = x.shape[0]

        rows = np.ceil(float(numFilt)/5)
        cols = 5
        
        # Compute opposing neighbors
        S, DN = self.opposing_neighbors(x, y, N)

        # Sigma array
        #sigarr = np.sqrt(DN[:,k-1].ravel())
        sigarr = np.ones(m)
        
        # Other inits
        C = -1*np.ones((m,N+1), dtype = np.int32)
        Pupd = np.zeros((m,m), dtype = np.int32)
        P = np.zeros((m,m), dtype = np.int32)
        inds = np.zeros(m, dtype = np.int32)

        #t1 = time()
        for j, r in enumerate(rho):
            # Re-initialize some arrays
            if j > 0:
                C.fill(-1)
                inds.fill(0)
                Pupd.fill(0)
            
            # Call Cython functions for updating P
            init_C_inds(C, inds)
            compute_C_closest(C, S, inds, DN, r, sigarr)
            update_P(C, inds, Pupd, 1)
            np.maximum(Pupd, Pupd.transpose(), out = Pupd)
            np.add(P, Pupd, out = P)

            nTriv[j] = np.sum(inds == 1)
            #sum(np.sum(C, axis = 0) == 1)

            if self.showComplexes:
                f = plt.figure(num = 1000, figsize = (rows*5, cols*5))
                titl = "r = " + str(r)
                self.show_simplicial_complex(x, y, Pupd.astype(np.double),
                                            f, rows, cols, j+1, titl)
            if self.saveComplexes:
                titl = "r = " + str(r)
                self.save_simplicial_complex(x, y, Pupd.astype(np.double),
                                             rows, cols, j+1, titl)
            
        P = numFilt - P

        return P, nTriv, numFilt, C

    def localscale_neighbors_opposing_r(self, x, y, k, rho):
        
        """ 
        nearest neighbors from opposing classes with local scale computed
        based on D and B
        (class other than that of the example considered)

        x - data points
        y - class membership
        k - nearest neighbors to be considered from opposing class for 
            computing local scale
        rho - List of multipliers to be used when computing the graph with
            local scale. For a value r from this, an edge will be created when
            d(x_i, x_j) < r*local_scale_i*local_scale_j and i, j belong to
            opposing classes
        
        2 hop neighbors are then computed to complete the triangles and form
        simplices
        """
    
        numFilt = len(rho)
        nTriv = np.zeros(numFilt)

        rows = np.ceil(float(numFilt)/5)
        cols = 5
        
        B, D = self.k_neighbors_opposing(x, y, k)

        # Sigma array
        sigarr = np.reshape(np.max(np.multiply(D, B), axis = 1), (-1,1))
        sigmat = np.dot(np.sqrt(sigarr), np.sqrt(sigarr.T)) #####
        
        C = np.zeros(D.shape)
        C1 = np.zeros(D.shape)
        C1bool = np.zeros(D.shape, dtype = np.bool)
        P = np.zeros(D.shape, dtype = np.int)

        # Mask specifying Trues for blocks where row and column have
        # same labels
        mask_mat = np.add(*[np.outer((y == uy), (y == uy))
                        for uy in np.unique(y)])

        for j, r in enumerate(rho):

            # Neighbors with local scale
            np.less_equal(D, r * sigmat, out = C)

            C[mask_mat] = 0.0

            # for i in range(x.shape[0]):
            #     same_inds = (y == y[i])
            #     C[i, same_inds] = 0.0
            #     C[same_inds, i] = 0.0

            # Set diagonals to 1
            np.fill_diagonal(C, 1.0)
            # np.dot(C, C, out = C1)
            np.dot(C, C.transpose(), out = C1)

            np.greater(C1, 0.0, out = C1bool)
            np.add(P,1, out = P, where = C1bool)

            nTriv[j] = sum(np.sum(C, axis = 0) == 1)

            if self.showComplexes:
                f = plt.figure(num = 1000, figsize = (rows*5, cols*5))
                titl = "r = " + str(r)
                self.show_simplicial_complex(x, y, C1bool.astype(np.double),
                                            f, rows, cols, j+1, titl)

            if self.saveComplexes:
                titl = "r = " + str(r)
                self.save_simplicial_complex(x, y, C1bool.astype(np.double),
                                             rows, cols, j+1, titl)

        P = numFilt - P

        return P, nTriv, numFilt 
    
    def localscale_neighbors_opposing_r_x(self, x, y, k, N, rho):
        
        """ 
        nearest neighbors from opposing classes with local scale computed
        based on D and B
        (class other than that of the example considered)

        x - data points
        y - class membership
        k - nearest neighbors to be considered from opposing class for 
            computing local scale
        rho - List of multipliers to be used when computing the graph with
            local scale. For a value r from this, an edge will be created when
            d(x_i, x_j) < r*local_scale_i*local_scale_j and i, j belong to
            opposing classes
        N - max number of nearest neighbors from opposing classes (user parameter)
        
        2 hop neighbors are then computed to complete the triangles and form
        simplices

        SIMILAR to localscale_neighbors_opposing_r but uses Cython for speedup
        This involves restricting the maximum number of neighbors for each point to N
        """
    
        numFilt = len(rho)
        nTriv = np.zeros(numFilt)
        m = x.shape[0]

        rows = np.ceil(float(numFilt)/5)
        cols = 5
        
        # Compute opposing neighbors
        S, DN = self.opposing_neighbors(x, y, N)

        # Sigma array
        sigarr = np.sqrt(DN[:,k-1].ravel())
        
        # Other inits
        C = -1*np.ones((m,N+1), dtype = np.int32)
        Pupd = np.zeros((m,m), dtype = np.int32)
        P = np.zeros((m,m), dtype = np.int32)
        inds = np.zeros(m, dtype = np.int32)

        #t1 = time()
        for j, r in enumerate(rho):
            # Re-initialize some arrays
            if j > 0:
                C.fill(-1)
                inds.fill(0)
                Pupd.fill(0)
            
            # Call Cython functions for updating P
            init_C_inds(C, inds)
            compute_C_closest(C, S, inds, DN, r, sigarr)
            update_P(C, inds, Pupd, 1)
            np.maximum(Pupd, Pupd.transpose(), out = Pupd)
            np.add(P, Pupd, out = P)

            nTriv[j] = np.sum(inds == 1)
            #sum(np.sum(C, axis = 0) == 1)

            if self.showComplexes:
                f = plt.figure(num = 1000, figsize = (rows*5, cols*5))
                titl = "r = " + str(r)
                self.show_simplicial_complex(x, y, Pupd.astype(np.double),
                                            f, rows, cols, j+1, titl)
            if self.saveComplexes:
                titl = "r = " + str(r)
                self.save_simplicial_complex(x, y, Pupd.astype(np.double),
                                             rows, cols, j+1, titl)
            
        P = numFilt - P

        return P, nTriv, numFilt, C

    def beta_skeleton_graph(self, ptcld, beta):
        
        """ Construct a beta skeleton graph for a point cloud and return the adjacency matrix
            ngl_exec - Full path of the executable compute-neighborhood of the ngl package
            (can be obtained from https://github.com/dhrieman/ngl)
            ptcld - numpy 2D array with each row corresponding to a point
            beta - beta value in the beta skeleton graph
        """
    
        import random
        import string
        import subprocess as sbp
        import os
        from scipy.sparse import coo_matrix, diags

        n = ptcld.shape[0]
        fdim = ptcld.shape[1]

        # Save the point cloud in a file
        fname = ''.join(random.choice(string.ascii_uppercase) for _ in range(10))
        fname = "intermediate/"+fname+".npy"
        np.savetxt(fname, ptcld)

        # Call the beta skeleton code
        p = sbp.Popen([self.ngl_exec, fname, str(fdim), "BSkeleton", str(beta)],
                      stdout=sbp.PIPE, stderr=sbp.PIPE)
        output = p.communicate()

        # Remove the data file
        if os.path.isfile(fname):
            os.remove(fname)

        if p.returncode != 0:
            raise Exception("Error with neighborhood graph computation (C++) - " + str(output[1]))
        else:
            edges = np.array([map(int, l.split(" ")) for l in output[0].strip().split("\n")])
            adj = coo_matrix((1.0*np.ones(edges.shape[0]), (edges[:,0], edges[:,1])), shape = (n, n)).todense().A
        
        self.beta_graph = {'edges': edges, 'adj': adj}
        
        return edges, adj
    
    def get_beta_graph(self):
        
        return self.beta_graph['adj']
    
    
    def beta_skeleton_graph_2classes(self, x, y, beta):
        
        """Similar to the function beta_skeleton_graph except that only neighbors in
            opposing classes are connected (as given by y)"""

        # First obtain a unsupervised beta skeleton graph
        edges, C = self.beta_skeleton_graph(x, beta)

        # Mask specifying Trues for blocks where row and column have
        # same labels
        mask_mat = np.add(*[np.outer((y == uy), (y == uy))
                        for uy in np.unique(y)])

        # Now remove neighbors in the same class
        C[mask_mat] = 0.0
        # for i in range(x.shape[0]):
        #     same_inds = (y == y[i])
        #     C[i, same_inds] = 0.0
        #     C[same_inds, i] = 0.0
     
        np.fill_diagonal(C, 1.0)
        
        return C
    
    def beta_opposing_simplex(self, x, y, beta):
        
        """ 
        nearest neighbors from opposing classes with local scale computed
        based on D and B
        (class other than that of the example considered)
        """
    
        P = np.zeros((x.shape[0], x.shape[0]), 
                     dtype = np.int)
        numFilt = len(beta)
        nTriv = np.zeros(numFilt)
        C1 = np.zeros(P.shape)
        C1bool = np.zeros(P.shape, dtype = np.bool)

        rows = np.ceil(float(numFilt)/5)
        cols = 5

        for j, b in enumerate(beta):
            
            C = self.beta_skeleton_graph_2classes(x, y, b)
            #C = np.double(np.dot(C, C) > 0)
            np.dot(C, C.transpose(), out = C1)

            np.greater(C1, 0.0, out = C1bool)
            np.add(P,1, out = P, where = C1bool)

            # P = P + C
            nTriv[j] = sum(np.sum(C, axis = 0) == 1)

            if self.showComplexes:
                f = plt.figure(num = 1000, figsize = (rows*5, cols*5))
                titl = "beta = " + str(beta[j])
                self.show_simplicial_complex(x, y, C1bool.astype(np.double),
                                             f, rows, cols, j+1, titl)

            if self.saveComplexes:
                titl = "r = " + str(r)
                self.save_simplicial_complex(x, y, C1bool.astype(np.double),
                                             rows, cols, j+1, titl)

        P = numFilt - P

        return P, nTriv, numFilt
        
    def show_simplicial_complex(self, x, y, C, f, rows, cols, i, titl):
        
        xx = [[(0,0), (0,0)]]
        ax = f.add_subplot(rows,cols,i)
        
        a, b = np.unique(y)
        
        t = x[y == a]
        s = x[y == b]
        ax.scatter(t[:,0], t[:, 1], color = 'b')
        ax.scatter(s[:,0], s[:, 1], color = 'r')
        
        for i1 in range(C.shape[0]):
            for i2 in range(C.shape[1]):
                if i1 != i2 and C[i1,i2] == 1.0:
                    xx.append([(x[i1,0], x[i1,1]), (x[i2,0], x[i2,1])])

        lc = mc.LineCollection(xx)
        ax.add_collection(lc)
        ax.autoscale()
        ax.set_title(titl)
        return 1

    def save_simplicial_complex(self, x, y, C, rows, cols, i, titl):
        
        f = plt.figure(num = 1000, figsize = (5, 5))

        xx = [[(0,0), (0,0)]]
        
        a, b = np.unique(y)
        
        t = x[y == a]
        s = x[y == b]
        # ax = plt.axes()
        ax = f.add_subplot(1,1,1)
        ax.scatter(t[:,0], t[:, 1], color = 'b')
        ax.scatter(s[:,0], s[:, 1], color = 'r')
        
        for i1 in range(C.shape[0]):
            for i2 in range(C.shape[1]):
                if i1 != i2 and C[i1,i2] == 1.0:
                    xx.append([(x[i1,0], x[i1,1]), (x[i2,0], x[i2,1])])

        lc = mc.LineCollection(xx)
        ax.add_collection(lc)
        ax.autoscale()
        ax.set_title(titl)

        f.savefig(os.path.join("results", "expt_"+str(self.exptid),
                    self.graphtype + "_complexes_" + str(i) + ".png"))
        return 1

    def save_distance_matrix(self, distance_matrix, filename):
        """ Saves distance matrix in the DIPHA format with the given
            filename
        """

        import numpy as np

        import subprocess
        import os
        import sys

        filename = os.path.abspath(filename)
        subprocess.call(["rm", filename])

        fid = open(filename, "wb")
        fid.write(np.array(8067171840).astype(np.int64))
        fid.write(np.array(7).astype(np.int64))
        fid.write(np.array(np.shape(distance_matrix)[1]).astype(np.int64))
        fid.write(distance_matrix.reshape(-1).astype(np.float64))
        # for i in range(np.shape(distance_matrix)[0]):
        #     for j in range(np.shape(distance_matrix)[1]):
        #         fid.write(np.array(distance_matrix[i, j]).astype(np.float64))
        fid.close()

    def load_persistence_diagram(self, fname, top_dim = None):

        import struct
        import numpy as np

        with open(fname, "rb") as f:

            assert struct.unpack('<q', f.read(8))[0] == 8067171840
            assert struct.unpack('<q', f.read(8))[0] == 2

            N = struct.unpack('<q', f.read(8))[0]

            dims = []
            birth_times = []
            death_times = []

            for i in range(0, N):
                (d, birth, death) = struct.unpack('<qdd', f.read(3*8))
                dims.append(d)
                birth_times.append(2 * birth)
                death_times.append(2 * death)

        return np.array(dims), np.array(birth_times), np.array(death_times)


    def dipha(self, dm, pdname, maxdim = 2):
        """
        # Homology dims start from 1 in this program
        # 1 - number of simply connected components
        # 2 - number of holes
        """

        import subprocess
        import os
        import sys
        import numpy as np

        dipha_path = os.path.abspath(self.dipha_path)
        distmat = os.path.abspath(dm)
        persdiag = os.path.abspath(pdname)

        print("Using program dipha to compute persistence diagrams")
        assert subprocess.call(["mpiexec", "-n", str(self.njobs), dipha_path, 
                                "--upper_dim", str(maxdim),  distmat, 
                                persdiag]) == 0
        # "--dual",

        dims, birth_values, death_values = self.load_persistence_diagram(pdname)

        death_values[dims < 0] = np.inf
        dims[dims < 0] = 0

        self.dims = dims
        self.birth_values = birth_values
        self.death_values = death_values

    def plotDiagram(self, pdname, dim, ax):

        displayPers(self.birth_values[self.dims == dim], \
                         self.death_values[self.dims == dim], 
                         "Persistence Diagram Betti " + str(dim), dim, ax)

    def run(self, save = True, show = False):

        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd

        import subprocess
        import os
        import sys

        dmname = os.path.abspath('intermediate/temp_distance_matrix')
        pdname = os.path.abspath('intermediate/temp_persdiag')

        subprocess.call(["rm", dmname])
        subprocess.call(["rm", pdname])

        print(np.max(self.P), np.min(self.P))

        self.save_distance_matrix(self.P, dmname)
        # Switch out dipha for ripser

        if self.PH_program == "dipha":
            self.dipha(dmname, pdname, maxdim = self.maxdim+1)
        elif self.PH_program == "ripser":
            self.dims, self.birth_values, self.death_values =\
                        ripser(dmname, pdname, 
                               maxdim = self.maxdim,
                               ripser_path = self.ripser_path)
        else:
            raise Exception("Unknown persistent homology program")
        
        # Separate program for simply connected components
        ncc, self.nTriv, _ = multi_conn_comp(self.P, self.numFilt)
     
        filtValues = np.linspace(0, self.numFilt, self.numFilt)
        self.bc = {d: None for d in pd.unique(self.dims)}

        for dim in pd.unique(self.dims):
            print("dimension %d" % (dim))

            if dim == 0:
                self.bc[dim] = ncc
            else:
                self.bc[dim] = bettiCounts(self.dims, self.birth_values, 
                                 self.death_values, filtValues, dim)

            #fig = plt.figure(num = dim + 1, figsize = (20, 4))
            fig = plt.figure(num = np.random.randint(1000000), 
                             figsize = (20, 4))
            ax1 = fig.add_subplot(131)
            self.plotDiagram(pdname, dim, ax1)

            ax2 = fig.add_subplot(132)
            ax2.plot(self.scale, self.bc[dim])
            ax2.autoscale()
            ax2.grid(True)
            ax2.set_title("Betti " + str(dim) + " Count")

            if dim == 0:

                temp = np.array(self.bc[dim] - self.nTriv)
                if len(temp[temp < 0]) > 0:
                    print "Pick a bigger scale parameter."

                ax3 = fig.add_subplot(133)
                ax3.plot(self.scale, self.bc[dim] - self.nTriv)
                ax3.autoscale()
                ax3.grid(True)
                ax3.set_title("Non-trivial Betti " + str(dim) + " Count")
            
            if save:
                plt.savefig(os.path.join("results", "expt_"+str(self.exptid),
                            self.graphtype + "_betti_" + str(dim) + ".png"))
            if show:
                plt.show()
            
        plt.clf()
        plt.close()
        
        out_dict = {"dist": self.P, "dims": self.dims, 
                    "birth": self.birth_values, "death": self.death_values,
                    "numFilt": self.numFilt, "nTriv": self.nTriv,
                    "filtValues": filtValues, "scale": self.scale}
        for dim in pd.unique(self.dims):
            out_dict["bc_"+str(int(dim))] = self.bc[dim]

        savemat(os.path.join("results", 
                             "expt_"+str(self.exptid), 
                             "out.mat"), out_dict)

    def opposing_neighbors(self, x, y, N):

        """ 
        All nearest neighbors from opposing classes 
        (class other than that of the example considered)       
        N - maximum number of nearest neighbors from opposing class that
            needs to be stored
        S - indices of neighbors (row-wise)
        DN - distances of neighbors (row-wise)
        """
        
        # D = distance.squareform(
        #             distance.pdist(x, metric = "euclidean"))
        D = pairwise_distances(x, metric="euclidean",
                               n_jobs=self.njobs)
        DN = -1.0*np.ones((x.shape[0], N))
        S = -1*np.ones((x.shape[0], N), dtype = np.int32)
        
        for i in range(x.shape[0]):
            yi = y[i]

            # Neighbor indices from other classes
            opp_ind = np.where(y != yi)[0]
            D_opp = D[i, opp_ind]
            
            n = np.minimum(len(D_opp), N)
            
            # Compute the distances and indices of nearest neighbors
            S[i, 0:n] = opp_ind[np.argsort(D_opp)[0:n]]
            DN[i, 0:n] = D[i, S[i,0:n]]

        return S, DN

    def k_neighbors_opposing(self, x, y, k):
        
        """ 
        K nearest neighbors from opposing classes 
        (class other than that of the example considered)
        """
        # D = distance.squareform(
        #         distance.pdist(x, metric = "euclidean"))
        D = pairwise_distances(x, metric="euclidean",
                               n_jobs=self.njobs)
        B = np.zeros((x.shape[0], x.shape[0]))
        for i in range(x.shape[0]):
            #xi = x[i,:] # is this used?
            yi = y[i]

            # Neighbor indices from other classes
            opp_ind = np.where(y != yi)[0]
            D_opp = D[i, opp_ind]
            opp_neigh_sort = np.argsort(D_opp)
            neigh_inds = opp_neigh_sort[0:int(k)]

            # D2 matrix with only the said neighbors preserved
            B[i, opp_ind[neigh_inds]] = 1.0

        return B, D

    def localscale_neighbors_opposing_r_old(self, x, y, k, rho):
        
        """ 
        nearest neighbors from opposing classes with local scale computed
        based on D and B
        (class other than that of the example considered)
        Older version of the code that is slightly slower than the current
        version.
        This cannot be speeded up much since the bottleneck is in np.dot
        of two big matrices to obtain the triangles. May be a more intelligent
        algorithm to obtain 2 hop neighbors may help
        """

        P = np.zeros(x.shape[0])
        numFilt = len(rho)
        nTriv = np.zeros(numFilt)

        rows = np.ceil(float(numFilt)/5)
        cols = 5
        f = plt.figure(num = 1000, figsize = (rows*5, cols*5))
        
        B, D = self.k_neighbors_opposing(x, y, k)

        for j, r in enumerate(rho):

            # Sigma array
            sigarr = np.reshape(np.max(np.multiply(D, B), axis = 1), (-1,1))
            sigmat = np.dot(np.sqrt(sigarr), np.sqrt(sigarr.T)) #####

            # Neighbors with local scale
            C = (D <= r * sigmat).astype(float)

            for i in range(x.shape[0]):
                same_inds = (y == y[i])
                C[i, same_inds] = 0.0
                C[same_inds, i] = 0.0

            # Set diagonals to 1
            np.fill_diagonal(C, 1.0)
            C = np.double(np.dot(C, C) > 0)
            P = P + C
            nTriv[j] = sum(np.sum(C, axis = 0) == 1)

            if self.showComplexes:
                titl = "r = " + str(r)
                self.show_simplicial_complex(x, y, C, f, rows, cols, j+1, titl)

        P = numFilt - P

        return P, nTriv, numFilt

    def localscale_neighbors_opposing_r_x_old(self, x, y, k, N, rho):
        
        """ 
        nearest neighbors from opposing classes with local scale computed
        based on D and B
        (class other than that of the example considered)

        x - data points
        y - class membership
        k - nearest neighbors to be considered from opposing class for 
            computing local scale
        rho - List of multipliers to be used when computing the graph with
            local scale. For a value r from this, an edge will be created when
            d(x_i, x_j) < r*local_scale_i*local_scale_j and i, j belong to
            opposing classes
        N - max number of nearest neighbors from opposing classes (user parameter)
        
        2 hop neighbors are then computed to complete the triangles and form
        simplices

        SAME as localscale_neighbors_opposing_r but uses Cython for speedup
        """
    
        numFilt = len(rho)
        nTriv = np.zeros(numFilt)
        m = x.shape[0]

        rows = np.ceil(float(numFilt)/5)
        cols = 5
        f = plt.figure(num = 1000, figsize = (rows*5, cols*5))
        
        B, D = self.k_neighbors_opposing(x, y, k)

        # Sigma array
        sigarr = np.sqrt(np.max(np.multiply(D, B), axis = 1))
        
        # Other inits
        C = -1*np.ones((m,N), dtype = np.int32)
        Pupd = np.zeros((m,m), dtype = np.int32)
        P = np.zeros((m,m), dtype = np.int32)
        inds = np.zeros(m, dtype = np.int32)

        for j, r in enumerate(rho):
            # Re-initialize some arrays
            if j > 0:
                C.fill(-1)
                inds.fill(0)
                Pupd.fill(0)
            
            # Call Cython functions for updating P
            init_C_inds(C, inds)
            compute_C(C, inds, D, r, sigarr, y)
            update_P(C, inds, Pupd, 1)
            np.maximum(Pupd, Pupd.transpose(), out = Pupd)
            np.add(P, Pupd, out = P)

            nTriv[j] = np.sum(inds == 1)
            #sum(np.sum(C, axis = 0) == 1)

            if self.showComplexes:
                titl = "r = " + str(r)
                self.show_simplicial_complex(x, y, Pupd.astype(np.double),
                                            f, rows, cols, j+1, titl)
            
        P = numFilt - P

        return P, nTriv, numFilt, C

def bettiCounts(dims, birth_values, death_values, filtValues, dim):

    import numpy as np

    bettiCounts = []

    N = len(filtValues)
    bettiCounts = np.zeros(N)
    intervals = getIntervals(birth_values, death_values, dims, dim)

    if intervals.size:
        for i in range(N):
            bettiCounts[i] = np.dot((intervals[:, 0] <= filtValues[i]).astype(int), \
                                    (intervals[:, 1] > filtValues[i]).astype(int))

    return bettiCounts

def getIntervals(birth_values, death_values, dims, dim):

    import numpy as np

    return np.column_stack([birth_values[dims == dim], 
                            death_values[dims == dim]])

def multi_conn_comp(P, numFilt):
    """
    Estimate singly and multiply connected components from P

    ncc - total connected components
    singly_conn - singly connected components
    multi_conn - multiply connected components
    """

    from scipy.sparse import csr_matrix, csgraph

    multi_conn = np.zeros(numFilt)
    singly_conn = np.zeros(numFilt)
    ncc = np.zeros(numFilt)
    for i in range(1, numFilt+1):
        P2 = (P < i).astype(np.int64)
        P2s = csr_matrix(P2)
        ncc[i-1], ccl = csgraph.connected_components(P2s)
        uv, cnts = np.unique(ccl, return_counts = True)
        singly_conn[i-1] = np.sum(cnts == 1)
        multi_conn[i-1] = ncc[i-1] - singly_conn[i-1]

    return ncc, singly_conn, multi_conn

def displayPers(births, deaths, title, dim, ax):

    import matplotlib.pyplot as plt

    birthst = deepcopy(births)
    deathst = deepcopy(deaths)
    birthst[np.isinf(birthst)] = np.nan
    deathst[np.isinf(deathst)] = np.nan

    maxv = np.maximum(np.nanmax(birthst), np.nanmax(deathst))
    minv = np.minimum(np.nanmin(birthst), np.nanmin(deathst))

    ax.scatter(births, deaths - births)
    ax.set_xlabel("birth time")
    ax.set_ylabel("life time")
    ax.set_title(title)
