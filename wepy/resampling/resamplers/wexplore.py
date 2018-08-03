import math
import random as rand
import itertools as it
from collections import namedtuple
from copy import copy
from copy import deepcopy

import numpy as np
import networkx as nx

from wepy.resampling.resamplers.resampler  import Resampler
from wepy.resampling.decisions.clone_merge import MultiCloneMergeDecision

class RegionTreeError(Exception):
    pass


## Merge methods

# algorithms for finding the number of mergeable walkers in a group
def calc_squashable_walkers_single_method(walker_weights, max_weight):

    # sort the weights smallest to biggest
    walker_weights.sort()

    # to get an estimate of the number of squashable walkers we start
    # summing the weights starting from the smallest walker. When the
    # addition of the next highest weight walker would make the total
    # greater than max_weight then we quit and say that the number of
    # squashable walkers is the number of them summed up, minus one
    # for the fact that one of them won't be squashed if a merge of
    # all of them was to occur
    n_squashable = 0

    idx = 0
    sum_weights = walker_weights[idx]
    merge_size = 1
    while sum_weights <= max_weight:

        # if the next index would be out of bounds break out of the
        # loop
        if idx + 1 >= len(walker_weights):
            break
        else:
            idx += 1

        # add this walker to the sum weights
        sum_weights += walker_weights[idx]

        # add one to the merge size (since we only will make our
        # estimate based on the single largest possible merge)
        merge_size += 1


    else:
        print("while-else found")
        # the loop condition failed so we remove the last count of
        # merge size from the merge group. This won't run if we break
        # out of the loop because of we are out of walkers to include
        merge_size -= 1


    # then we also take one less than that as the number of
    # squashable walkers
    n_squashable = merge_size - 1


    return n_squashable


# algorithms for actually generating the merge groups
def decide_merge_groups_single_method(walker_weights, balance, max_weight):

    assert balance < 0, "target balance must be negative"

    # the number of walkers we need to choose in order to be
    # able to do the required amount of merges
    num_merge_walkers = abs(balance) + 1

    # select the lowest weight walkers to use for merging, these
    # are idxs on the mergeable walkers and not the walker_idxs
    chosen_idxs = np.argsort(walker_weights)[:num_merge_walkers]

    # check that this is not greater than the max weight
    if sum([walker_weights[chosen_idx] for chosen_idx in chosen_idxs]) > max_weight:
        result = False
    else:
        result = True

    # return the chosen idxs as the sole full merge group
    return [chosen_idxs], result

## Clone methods
def calc_max_num_clones(walker_weights, min_weight, max_num_walkers):

    # initialize an array for the counts of each walker given
    max_n_clones = [0 for weight in walker_weights]

    # go through each weight and calculate its max clones for it
    for idx, walker_weight in enumerate(walker_weights):

        # start with a two splitting
        n_splits = 2
        # then increase it every time it passes or until we get to the
        # max number of walkers
        while ((walker_weight / n_splits) >= min_weight) and \
              (n_splits <= max_num_walkers):
            if n_splits % 100 == 0:
                print(n_splits)
            n_splits += 1

        # the last step failed so the number of splits is one less
        # then we counted
        n_splits -= 1

        # we want the number of clones so we subtract one from the
        # number of splits to get that, and we save this for this
        # walker
        max_n_clones[idx] = n_splits - 1

    return max_n_clones


class RegionTree(nx.DiGraph):

    # the strings for choosing a method of solving how deciding how
    # many walkers can be merged together given a group of walkers and
    # the associated algorithm for actually choosing them
    MERGE_METHODS = ('single',)

    # Description of the methods

    # 'single' : this method simplifies the problem (likely giving
    # very suboptimal solutions especially early in sampling when
    # walkers are of similar large weights) by enforcing that within a
    # group of walkers (i.e. in a leaf region node) only one merge
    # will take place. To decide how large a given merge group can be
    # then is simply found by consecutively summing the weights of the
    # smallest walkers until the inclusion of the next highest
    # violates the maximum weight. Thus the algorithm for actually
    # finding the walkers that shall be merged is as simple as taking
    # the K lowest walkers given by the first algorithm. This is then
    # guaranteed to satisfy the potential.

    # as further methods are mathematically proven and algorithms
    # designed this will be the chosen method.

    ROOT_NODE = ()

    def __init__(self, init_state,
                 max_n_regions=None,
                 max_region_sizes=None,
                 max_num_walkers=None,
                 min_num_walkers=1,
                 distance=None,
                 pmin=None, pmax=None,
                 merge_method='single'):

        super().__init__()

        if (max_n_regions is None) or \
           (max_region_sizes is None) or \
           (distance is None) or \
           (pmin is None) or \
           (pmax is None):
            raise ValueError("All parameters must be defined, 1 or more are missing.")

        self._max_n_regions = max_n_regions
        self._n_levels = len(max_n_regions)
        self._max_region_sizes = max_region_sizes
        self._distance = distance
        self._pmin = pmin
        self._pmax = pmax
        self._max_num_walkers = max_num_walkers
        self._min_num_walkers = min_num_walkers

        assert merge_method in self.MERGE_METHODS, \
            "the merge method given, '{}', must be one of the methods available {}".format(
                merge_method, self.MERGE_METHODS)

        print(merge_method)
        self._merge_method = merge_method

        self._walker_weights = []
        self._walker_assignments = []

        image_idx = 0
        # get the image using the distance object
        image = self.distance.image(init_state)
        self._images = [image]

        parent_id = self.ROOT_NODE
        self.add_node(parent_id, image_idx=0,
                      n_walkers=0,
                      n_mergeable=0,
                      n_cloneable=0,
                      balance=0,
                      walker_idxs=[])

        # make the first branch
        for level in range(len(max_n_regions)):
            child_id = parent_id + (0,)
            self.add_node(child_id, image_idx=image_idx,
                          n_walkers=0,
                          n_mergeable=0,
                          n_cloneable=0,
                          balance=0,
                          walker_idxs=[])
            self.add_edge(parent_id, child_id)
            parent_id = child_id

        # add the region for this branch to the regions list
        self._regions = [tuple([0 for i in range(self._n_levels)])]

    @property
    def merge_method(self):
        return self._merge_method

    @property
    def distance(self):
        return self._distance

    @property
    def images(self):
        return self._images

    @property
    def max_n_regions(self):
        return self._max_n_regions

    @property
    def n_levels(self):
        return self._n_levels

    @property
    def max_region_sizes(self):
        return self._max_region_sizes

    @property
    def max_num_walkers(self):
        return self._max_num_walkers

    @property
    def min_num_walkers(self):
        return self._min_num_walkers

    @property
    def pmin(self):
        return self._pmin

    @property
    def pmax(self):
        return self._pmax

    @property
    def walker_assignments(self):
        return self._walker_assignments

    @property
    def walker_weights(self):
        return self._walker_weights

    @property
    def regions(self):
        return self._regions

    def add_child(self, parent_id, image_idx):
        # make a new child id which will be the next index of the
        # child with the parent id
        child_id = parent_id + (len(self.children(parent_id)), )

        # create the node with the image_idx
        self.add_node(child_id,
                      image_idx=image_idx,
                      n_walkers=0,
                      n_mergeable=0,
                      n_cloneable=0,
                      balance=0,
                      walker_idxs=[])

        # make the edge to the child
        self.add_edge(parent_id, child_id)

        return child_id

    def children(self, parent_id):
        children_ids = list(self.adj[parent_id].keys())
        # sort them
        children_ids.sort()
        return children_ids

    def level_nodes(self, level):
        """Get the nodes/regions at the specified level."""

        if level > self.n_levels:
            raise ValueError("level is greater than the number of levels for this tree")

        return [node_id for node_id in self.nodes
                if len(node_id) == level]

    def leaf_nodes(self):
        return self.level_nodes(self.n_levels)

    def branch_tree(self, parent_id, image):
        # add the new image to the image index
        image_idx = len(self._images)
        self._images.append(image)

        branch_level = len(parent_id)
        # go down from there and create children
        for level in range(branch_level, self.n_levels):
            child_id = self.add_child(parent_id, image_idx)
            parent_id = child_id

        #add new assignment  to the image assignments
        self._regions.append(child_id)
        # return the leaf node id of the new branch
        return child_id

    def assign(self, state):

        assignment = []
        dists = []

        # a cache for the distance calculations so they need not be
        # performed more than once
        dist_cache = {}

        # perform a n-ary search through the hierarchy of regions by
        # performing a distance calculation to the images at each
        # level starting at the top
        node = self.ROOT_NODE
        for level in range(self.n_levels):
            level_nodes = self.children(node)

            # perform a distance calculation to all nodes at this
            # level
            image_dists = []
            for level_node in level_nodes:

                # get the image
                image_idx = self.node[level_node]['image_idx']
                image = self.images[image_idx]

                # if this distance is already calculated don't
                # calculate it again and just get it from the cache
                if image_idx in dist_cache:
                    dist = dist_cache[image_idx]
                # otherwise calculate it and save it in the cache
                else:
                    # image of the state
                    state_image = self.distance.image(state)

                    # there is the possibility of
                    try:
                        dist = self.distance.image_distance(state_image, image)
                    except ValueError:
                        print("state: ", state.dict())
                        print("state_image: ", state_image)
                        print("image: ", image)
                        raise ValueError("If you have triggered this error you have"
                                         " encountered a rare bug. Please attempt to"
                                         " report this using the printed outputs.")

                    # save in the dist_cache
                    dist_cache[image_idx] = dist

                # add it to the dists for this state
                image_dists.append(dist)

            # get the index of the image that is closest
            level_closest_child_idx = np.argmin(image_dists)
            # get the distance for the closest image
            level_closest_image_dist = image_dists[level_closest_child_idx]

            # save for return
            assignment.append(level_closest_child_idx)
            dists.append(level_closest_image_dist)

            # set this node as the next node
            node = level_nodes[level_closest_child_idx]

        return tuple(assignment), tuple(dists)

    def clear_walkers(self):
        """Remove all walkers from the regions."""

        # reset the walker assignments to an empty list
        self._walker_assignments = []
        self._walker_weights = []

        # set all the node attributes to their defaults
        for node_id in self.nodes:
            self.node[node_id]['n_walkers'] = 0
            self.node[node_id]['walker_idxs'] = []

            self.node[node_id]['n_squashable'] = 0
            self.node[node_id]['n_possible_clones'] = 0
            self.node[node_id]['balance'] = 0


    def place_walkers(self, walkers):

        # clear all the walkers and reset node attributes to defaults
        self.clear_walkers()

        # keep track of new branches made
        new_branches = []

        # place each walker
        for walker_idx, walker in enumerate(walkers):

            # assign the state of the walker to the tree and get the
            # distances to the images at each level
            assignment, distances = self.assign(walker.state)

            # check the distances going down the levels to see if a
            # branching (region creation) is necessary
            for level, distance in enumerate(distances):

                # if we are over the max region distance and we are
                # not above max number of regions we have found a new
                # region so we branch the region_tree at that level
                if distance > self.max_region_sizes[level] and \
                   len(self.children(assignment[:level])) < self.max_n_regions[level]:

                    # make an image for the region
                    image = self.distance.image(walker.state)
                    parent_id = assignment[:level]

                    # make the new branch
                    assignment = self.branch_tree(parent_id, image)

                    # save it to keep track of new branches as they occur
                    new_branches.append({'distance' : np.array([distance]),
                                         'branching_level' : np.array([level]),
                                         'new_leaf_id' : np.array(assignment),
                                         'image' : image,})

                    # we have made a new branch so we don't need to
                    # continue this loop
                    break

            # save the walker assignment
            self._walker_assignments.append(assignment)
            self._walker_weights.append(walker.weight)

            # go back through the nodes in this walker's branch
            # increase the n_walkers for each node, and save the
            # walkers (index in self.walker_assignments) it has, and
            # save increase the number above pmin if valid
            for level in range(len(assignment) + 1):
                node_id = assignment[:level]

                self.node[node_id]['n_walkers'] += 1
                self.node[node_id]['walker_idxs'].append(walker_idx)


        # TODO: DO we really need to do this here!!

        # after placing all the walkers we calculate the number of
        # reducible walkers for each node for each leaf node calculate
        # the number of reducible walkers (i.e. the largest possible
        # number of merges that could occur taking into account the
        # pmax (max weight) constraint) and the number of possible
        # clones
        for node_id in self.leaf_nodes():

            leaf_walker_idxs = self.node[node_id]['walker_idxs']
            leaf_weights = [self.walker_weights[i] for i in leaf_walker_idxs]

            # first we see how many merges we can do. FIrst we check
            # to see there are more than 1 walker so we can actually
            # do a merge
            if self.node[node_id]['n_walkers'] > 1:

                # figure out the most possible mergeable walkers
                # assuming they cannot ever be larger than pmax
                self.node[node_id]['n_mergeable'] = self._calc_mergeable_walkers(leaf_weights)

                # increase the reducible walkers for the higher nodes
                # in this leaf's branch
                for level in reversed(range(self.n_levels)):
                    branch_node_id = node_id[:level]
                    self.node[branch_node_id]['n_mergeable'] += self.node[node_id]['n_mergeable']

            # now we figure out how many clones are possible, we only
            # need one walker to have potential clones
            if self.node[node_id]['n_walkers'] > 0:

                # get the max number of clones for each walker and sum
                # them up to get the total number of cloneable walkers
                self.node[node_id]['n_cloneable'] = sum(self._calc_max_num_clones(leaf_weights))

                # propagate this up the tree summing to get a number
                # for the higher levels
                for level in reversed(range(self.n_levels)):
                    branch_node_id = node_id[:level]
                    self.node[branch_node_id]['n_cloneable'] += self.node[node_id]['n_cloneable']


        return new_branches

    @classmethod
    def _max_n_merges(cls, pmax, root, weights):

        # indices of the weights
        walker_idxs = [i for i, weight in enumerate(weights)]

        # remove the root from the weights
        unused_walker_idxs = list(set(walker_idxs).difference(root))

        # initialize the number of merges identified by the length of
        # the current root
        max_n_merges = len(root) - 1


        # then combine the root with the unused weights
        for root, merge_candidate in it.product([root], unused_walker_idxs):

            # get the weights for this combo
            combo_weights = [weights[i] for i in root] + [weights[merge_candidate]]

            # sum them
            sum_weight = sum(combo_weights)

            # if the sum of the weights is less than or equal than the
            # pmax then this combination beats the current record of
            # the root
            if sum_weight <= pmax:

                # then we know that the number of merges is at least
                # one more than the root
                max_n_merges += 1

                # if we still haven't reached the pmax continue making
                # merges to see if we can beat this record
                if sum_weight < pmax:

                    # make a new root for this combo and recursively call
                    # this method
                    new_combo = (*root, merge_candidate,)

                    # this will return the maximum number of merges from
                    # this subset of the walkers
                    n_merges = cls._max_n_merges(pmax, new_combo, weights)

                    # if this is greater than the current record
                    # overwrite it
                    if n_merges > max_n_merges:
                        max_n_merges = n_merges

                # if it is exactly pmax then no more merges can be
                # done so we can just end here and return this record
                elif sum_weight == pmax:
                    break


        # if no combination of this root and other candidates can make
        # any more merges than we just return the roots number of merges

        return max_n_merges

    def _calc_mergeable_walkers(self, walker_weights):

        if self.merge_method == 'single':
            n_mergeable = calc_mergeable_walkers_single_method(walker_weights, self.pmax)
        else:
            raise ValueError("merge method {} not recognized".format(self.merge_method))

        return n_mergeable

    def _calc_max_num_clones(self, walker_weights):

        return calc_max_num_clones(walker_weights, self.pmin, self.max_num_walkers)

    def _propagate_and_balance_shares(self, parental_balance, children_node_ids):

        # talk about "shares" which basically are the number of
        # slots/replicas that will be allocated to this region for
        # running sampling on

        # Our first goal in this subroutine is to dispense a parental
        # balance to it's children in a simply valid manner
        children_shares = self._dispense_parental_shares(parental_balance, children_node_ids)

        # Now that we have dispensed the shares to the children in a
        # valid way we use an algorithm to now distribute the shares
        # between the regions as evenly as possible
        children_net_balances = self._balance_children_shares(children_shares)

        # no state changes to the object have been made up until this
        # point, but now that the net change in the balances for the
        # children have been generated we set them into their nodes
        for child_node_id, child_net_balance in children_net_balances.items():

            self.node[child_node_id]['balance'] = child_net_balance


    def _dispense_parental_shares(self, parental_balance, children_node_ids):
        """Given a parental balance and a set of children nodes, we dispense
        the shares indicated by the balance to the children nodes in a
        VALID but not necessarily optimal or desirable way. This
        merely checks for the hard constraints on the number of shares
        a region can either give or receive based on their capacity to
        clone and merge walkers.

        An additional balancing step can be performed to redistribute them.

        """

        # if there is only one child it just inherits all of the
        # balance no matter what
        if len(children_node_ids) == 1:

            # increase the balance of the only child
            self.node[children_node_ids[0]]['balance'] = parental_balance

        # there are more than one child so we accredit balances
        # between them
        elif len(children_node_ids) > 1:

            # if the parent has a non-zero balance we either
            # increase (clone) or decrease (merge) the balance

            # these poor children are inheriting a debt and must
            # decrease the total number of their shares :(
            if parental_balance < 0:

                children_shares = self._dispense_debit_shares(parental_balance, children_node_ids)

            # these lucky children are inheriting a positive number of
            # shares!! :)
            elif parental_balance > 0:

                children_shares = self._dispense_credit_shares(parental_balance, children_node_ids)

        return children_shares

    def _dispense_debit_shares(self, parental_balance, children_node_ids):
        """For a negative parental balance we dispense it to the children
        nodes"""

        # the number of shares for each region before the
        # balancing/resampling we are doing here is equal just to the
        # number of walkers they have
        children_shares = {child_id : self.node[child_id]['walker_idxs']
                           for child_id in children_node_ids}

        # dispense the negative shares as quickly as possible,
        # they will be balanced later
        child_idx = 0
        while remaining_balance < 0:
            # get the node id
            child_node_id = children_node_ids[child_idx]

            n_squashable = self.node[child_node_id]['n_squashable']

            # if this child has any squashable walkers
            if n_squashable > 0:

                # we use those for paying the parent's debt

                # the amount of the parental debt that can be
                # paid (the payment) for this child region is
                # either the number of squashable walkers or
                # the absolute value of the parental balance
                # (since it is negative for debts), whichever
                # is smaller
                payment = min(n_squashable, abs(parental_balance))

                # take this from the remaining balance
                remaining_balance += payment

                # and take it away from the childs due balance and shares
                children_shares[node_id] -= payment

        # if the parental balance is still not zero the
        # children cannot balance it given their constraints
        # and there is an error
        if parental_balance < 0:
            raise ValueError("Children cannot pay their parent's debt")

        # double check the balance is precisely 0, we want to
        # dispense all the shares as well as not accidentally
        # overdispensing
        assert remaining_balance == 0, "balance is not 0"


        return children_shares

    def _dispense_credit_shares(self, parental_balance, children_node_ids):

        # the number of shares for each region before the
        # balancing/resampling we are doing here is equal just to the
        # number of walkers they have
        children_shares = {child_id : self.node[child_id]['walker_idxs']
                           for child_id in children_node_ids}

        # dispense the shares to the able children as quickly
        # as possible, they will be redistributed in the next
        # step
        child_idx = 0
        while remaining_balance > 0:
            # get the node id
            child_node_id = children_node_ids[child_idx]

            # give as much of the parental balance as we can
            # to the walkers. In the next step all this
            # balance will be shared among the children so all
            # we need to do is dispense all the shares without
            # care as to who gets them, as long as they can
            # keep it
            n_possible_clones = self.node[child_node_id]['n_possible_clones']

            # the amount to be disbursed to this region is
            # either the number of possible clones (the
            # maximum it can receive) or the full parental
            # balance, whichever is smaller
            disbursement = min(n_possible_clones, abs(parental_balance))

            # give this disbursement by taking away from the
            # positive balance
            remaining_balance -= disbursement

            # add these shares to the net balances and share
            # totals
            children_shares[node_id] += payment

            # go to the next child node
            child_idx += 1

        # if the parental balance is still not zero the
        # children cannot balance it given their constraints
        if parental_balance > 0:
            raise ValueError("Children cannot accept all parental shares of the balance")

        # double check the balance is precisely 0, we want to
        # dispense all the shares as well as not accidentally
        # overdispensing
        assert remaining_balance == 0, "balance is not 0"

        return children_shares




    def _gen_best_donation(self, children_shares):
        """Given a the children shares generate the best donation. Returns the
        donor_node_id the acceptor_node_id and the donation that
        should be done between them and that will be guaranteed to be
        valid. (this is done by checking the attributes of the regions
        node however, no changes to node state are performed)

        returns donor_node_id, acceptor_node_id, donation_amount

        """

        # first find the pair of node regions that will give the best
        # donation outcome
        result = self._find_best_donation_pair(children_shares)

        # if the result is False then no possible donation could be
        # found, so we set the donation amount to 0, the loop will not
        # enter and the balancing will be considered done
        if not result:
            donor_node_id = None
            acceptor_node_id = None
            donation_amount = 0

        # otherwise we figure out what the appropriate donation
        # actually is and account for it
        else:
            donor_node_id, acceptor_node_id = result

            # calculate the number of share donations to take from
            # the max child and give to the min child
            donation_amount = self._calc_share_donation(max_child_node_id,
                                                        min_child_node_id,
                                                        children_shares)

        return donor_node_id, acceptor_node_id, donation_amount


    def _balance_children_shares(self, children_shares):
        """Given a dictionary mapping the child node_ids to the total number
        of shares they currently hold we balance between them in order
        to get an even distribution of the shares as possible.

        """

        # this is the net change in balance that will be generated by
        # this subroutine
        children_net_balances = {child_node_id : 0 for child_node_id in children_node_ids}

        # generate the actual donation pair and the amount that should
        # be donated for the best outcome
        donor_node_id, acceptor_node_id, donation_amount = self._gen_best_donation(children_shares)

        # account for this donation in the net changes in the net balances and the total shares
        children_net_balances[donor_node_id] -= n_shares
        children_net_balances[acceptor_node_id] += n_shares

        # and the total shares
        children_shares[donor_node_id] -= n_shares
        children_shares[acceptor_node_id] += n_shares

        # we have decided the first donation, however more will be
        # performed as long as the amount of the donation is either 0
        # or that two donations of only 1 share occur twice in a
        # row. The former occurs in scenarios when there is an even
        # balance and the latter in an odd scenario and the last odd
        # share would get passed back and forth

        # we keep track of the previous donation, and initialize it to
        # None for now
        previous_donation_amount = None

        while (donation_amount > 0) and \
              not (previous_donation_amount == 1 and donation_amount == 1):

            # get the next best donation
            donor_node_id, acceptor_node_id, donation_amount = self._gen_best_donation(children_shares)

            # account for this donation in the net changes in balances
            children_net_balances[donor_node_id] -= n_shares
            children_net_balances[acceptor_node_id] += n_shares

            # and the total shares
            children_shares[donor_node_id] -= n_shares
            children_shares[acceptor_node_id] += n_shares

            # update the previous donation amount
            previous_donation_amount = donation_amount

        return children_net_balances

    def _find_best_donation_pair(self, children_shares):
        """This method just returns which children have the most and least
        number of 'shares' which are the effective number of walker
        slots it will be granted in the next segment of dynamics in
        the simulation. This is essentially the amount of sampling
        effort that will be allocated to this region.

        This method is give the dictionary of the childrens

        """

        # one region will be the donor of shares
        donor_child_node_id = None

        # the other will accept them
        acceptor_child_node_id = None

        # record for maximum number of donateable shares
        max_donatable_shares = None

        # records for the max and min number of shares of the acceptor
        # and donor regions
        donor_n_shares = None
        acceptor_n_shares = None

        # go through every walker and test it to see if it is either
        # the highest or lowest, record it if it is
        for child_node_id, n_shares in enumerate(children_shares):

            # the number of donatable shares is equal to the number
            # of squashable walkers
            n_donatable_shares = self.node[child_node_id]['n_squashable']

            # the number of possible shares this node can receive is
            # equal to the number of possible clones it can make
            n_receivable_shares = self.node[child_node_id]['n_possible_clones']

            # we see if this node region is the max region by testing
            # if it is the new highest in shares. It must also be able
            # to donate a share by having at least 1 squashable walker
            if ((donor_child_node_id is None) or (n_shares >  donor_n_shares)) and \
               (n_donatable_shares > 0):

                # this is a new record
                max_donatable_shares = n_donatable_shares

                # save how many shares this region has in total
                donor_n_shares = n_shares
                donor_child_node_id = child_node_id


            # test if this is the region with the lowest number of
            # shares that is still able to receive at least one share
            if ((acceptor_child_node_id is None) or (n_shares < acceptor_n_shares)) and \
               (n_receivable_shares > 0):

                acceptor_n_shares = n_shares
                acceptor_child_node_id = child_node_id

        # check that both a donor and acceptor were identified and
        # that values for there shares were given
        assert all([True if val is not None else False
                    for val in [donor_n_shares, acceptor_n_shares,
                                donor_child_node_id, acceptor_child_node_id]]), \
                "A donor or acceptor was not found"

        # if the acceptor's number of shares is not less then the
        # donor then there is not possible donation
        if acceptor_n_shares >= donor_n_shares:
            return False
        # if there is a net donation we return the donor and acceptor
        else:
            return donor_child_node_id, acceptor_child_node_id

    def _calc_share_donation(self, donor_node_id, recipient_node_id, children_shares):

        # get the total shares each child node region has
        donor_n_shares = children_shares[donor_node_id]
        acceptor_n_shares = children_shares[acceptor_node_id]

        # then we get the total number of donatable shares the donor
        # actually has
        n_donatable_shares = self.node[child_node_id]['n_squashable']

        # the sibling with the greater number of shares (from both
        # previous resamplings and inherited from the parent) will
        # give shares to the sibling with the least.

        # To decide how many it shall give we first propose a desired
        # donation that will make them the most similar, rounding down
        # (i.e. midpoint)
        desired_donation = math.floor((donor_n_shares - recipient_n_shares)/2)

        # however, the donor only has a certain capability of donation
        # if this is lower than the desired donation then we donate
        # all that this region has
        actual_donation = min(desired_donation, n_donatable_shares)

        return actual_donation

    def _decide_merge_leaf(self, leaf, merge_groups):

        # this method assumes no cloning has been performed before this

        # TODO: potentially unneeded
        # all the walker idxs
        walker_idxs = list(range(len(merge_groups)))

        # the balance of this leaf
        leaf_balance = self.node[leaf]['balance']

        # there should not be any taken walkers in this leaf since a
        # leaf should only have this method run for it once during
        # decision making, so the mergeable walkers are just all the
        # walkers in this leaf
        leaf_walker_idxs = self.node[leaf]['walker_idxs']
        leaf_walker_weights = [self.walker_weights[walker_idx] for walker_idx in leaf_walker_idxs]


        # now that we have the walkers that may potentially be merged
        # we need to actually find a set of groupings that satisfies
        # the reduction in balance without any individual walker
        # exceeding the maximum weight. In general this is a difficult
        # problem both here and in deciding how balances are
        # distributed (because the potential merges determine a leafs
        # ability to pay a portion of a debt from a higher level in
        # the region tree).

        # currently we avoid this general problem (potentially of the
        # backpack kind if you want to help solve this issue) and
        # simply assume that we will perform a single merge of the
        # walkers of the lowest weights to achieve our balance
        # reduction goal. As long as this assumption holds in how the
        # balances are determined this will succeed, if not this will
        # fail

        # to allow for easy improvements later on pending this problem
        # becoming solved it is functionalized here to make a set of
        # pairings that satisfy the balance reduction goal, these are
        # "merge groups" except that at this point we haven't chosen
        # one to be the KEEP_MERGE walker and have its state
        # retained. This will be decided further on. So these "full
        # merge groups" include all the walkers that will be merged
        # and the sum of their weights will be the weight of the final
        # merged walker and should satisfy the maximum weight
        # requirement, i.e. it will not be checked here.
        full_merge_groups_leaf_walker_idxs = \
                                self.solve_merge_groupings(leaf_walker_weights, leaf_balance)

        # now we go through each of these "full merge groups" and make
        # the "merge groups". Pardon the terminology, but the
        # distinction is trivial and is only relevant to the
        # implementation. The "merge groups" are what is returned. To
        # make them we just choose which walker to keep and which
        # walkers to squash in each full merge group
        for full_merge_group_leaf_walker_idxs in full_merge_groups_leaf_walker_idxs:

            # the indices from this are in terms of the list of weights
            # given to the method so we translate them back to the actual
            # walker indices
            chosen_walker_idxs = [leaf_walker_idxs[leaf_walker_idx]
                                  for leaf_walker_idx in full_merge_group_leaf_walker_idxs]

            # get the weights of these chosen_walker_idxs
            chosen_weights = [self.walker_weights[walker_idx] for walker_idx in chosen_walker_idxs]

            # choose the one to keep the state of (e.g. KEEP_MERGE
            # in the Decision) based on their weights

            # normalize weights to the sum of all the chosen weights
            chosen_pdist = chosen_weights / sum(chosen_weights)

            # then choose one of the the walker idxs to keep according to
            # their normalized weights
            keep_walker_idx = np.random.choice(chosen_walker_idxs, 1, p=chosen_pdist)[0]

            # pop the keep idx from the walkers so we can use the rest of
            # them as the squash idxs
            chosen_walker_idxs.pop(chosen_walker_idxs.index(keep_walker_idx))

            # the rest are squash_idxs
            squash_walker_idxs = chosen_walker_idxs

            # update the merge group based on this decision
            merge_groups[keep_walker_idx].extend(squash_walker_idxs)

        return merge_groups

    def solve_merge_groupings(self, walker_weights, balance):

        # this method chooses between the methods for solving the
        # backpack problem of how to merge walkers together to satisfy
        # a goal

        # as a method for easy transition between potential methods (I
        # expect there are multiple solutions to the problem with
        # different tradeoffs that will want to be tested) a method
        # can be chosen when the region tree is created and a constant
        # string identifier will be set indicating which method is in use

        # so we use that string to find which method to use
        if self.merge_method == 'single':
            full_merge_groups, result = single_merge_method(walker_weights, balance, self.pmax)

        else:
            raise ValueError("merge method {} not recognized".format(self.merge_method))

        # if the result came out false then a solution could not be
        # found
        if not result:
            raise RegionTreeError(
                "A solution to the merging problem could not be found given the constraints")

        else:
            return full_merge_groups

    def _decide_clone_leaf(self, leaf, merge_groups, walkers_num_clones):

        # this assumes that the all squashes have already been
        # specified in the merge group, this is so that we can use
        # unused walker slots.

        # if this leaf node was assigned a debt we need to merge
        # walkers
        leaf_balance = self.node[leaf]['balance']
        leaf_walker_idxs = self.node[leaf]['walker_idxs']
        leaf_weights = [self.walker_weights[walker_idx]
                        for walker_idx in self.node[leaf]['walker_idxs']]

        # all of the squashed walkers from the merge groups leave
        # behind slots we can fill with cloned walkers, we acquire
        # these slots
        free_slot_idxs = list(it.chain(merge_groups))

        # we also need to choose walkers for cloning which cannot be
        # either squashed or merged walkers
        taken_walker_idxs = list(it.chain([[keep_idx, *squashed_idxs]
                                           for keep_idx, squashed_idxs in merge_groups
                                           if len(squashed_idxs) > 0]))

        # get the idxs of the cloneable walkers that when split at
        # least 1 time will have children with weights equal to or
        # greater than the pmin, also we have the condition that they
        # are not already taken for merging
        cloneable_walker_idxs, cloneable_walker_weights = \
                                zip(*[(walker_idx, weight) for walker_idx, weight
                                      in zip(leaf_walker_idxs, leaf_weights)
                                      if (weight/2 >= self.pmin) and
                                         (walker_idx not in taken_walker_idxs)])

        # each walker can only be cloned until it would produce a
        # walker less than the pmin, so we figure out the maximum
        # number of splittings of the weight each cloneable walker can
        # do. initialize to 0 for each
        max_n_clones = self._calc_max_num_clones(cloneable_walker_weights)

        # the sum of the possible clones needs to be greater than or
        # equal to the balance
        assert sum(max_n_clones) >= leaf_balance, \
            "there isn't enough clones possible to pay the balance"

        # to distribute the clones we iteratively choose the walker
        # with the highest weight after amplification weight/(n_clones
        # +1) where n_clones is the current number of clones assigned
        # to it (plus itself)
        clones_left = leaf_balance
        while clones_left > 0:

            # calculate the weights of the walker's children given the
            # current number of clones, if num_clones is 0 then it is
            # just it's own weight
            child_weights = []
            for walker_idx, weight in zip(cloneable_walker_idxs, cloneable_walker_weights):

                # the weight of its children given the number of
                # clones already assigned to it
                child_weight = weight / (walkers_num_clones[walker_idx]+1)

                # TODO: this strict adherence to the pmin is not
                # supported by the way the number of possible clones
                # for a leaf region are calculated and thus when we
                # stick to strict adherence there are potentially
                # situations a positive balance is assigned according
                # to the method that allows children to be less than
                # pmin that then REQUIRES this leaf produce that many
                # when in reality it cannot because the strict method
                # generates less possible children. So until strict
                # pmin adherence is observed by the balancing
                # subroutines then this cannot be used. Of course I
                # would add that repeated cloning of a walker that
                # originally was above the pmin but is cloned many
                # times could get walkers that are significantly lower
                # than the pmin.

                # if this child weight is less than the pmin then this
                # one has maxed out on the number of clones it can do
                # so we set the child weight to -1. When we select a
                # walker to clone below we always select the one with
                # the highest child weight and since all real child
                # weights should be greater than zero (except
                # accounting for floating point tolerances) so these
                # will never be selected unless all cloneable walkers
                # are used up, which was already checked for above
                # that it could not happen
                if child_weight < self.pmin:
                    child_weight = -1

                child_weights.append(child_weight)

            # just a double check (triple check?) that they are not all -1 values
            assert not all([True if child_weight == -1 else False
                            for child_weight in child_weights]), \
                                "All walkers are unable to produce children over the pmin"

            # get the walker_idx with the highest current child weight
            chosen_walker_idx = cloneable_walker_idxs[np.argsort(child_weights)[-1]]

            # add a clone to it
            walkers_num_clones[chosen_walker_idx] += 1

            # we are one step closer to satisfying the cloning
            # requirement
            clones_left -= 1

        return walkers_num_clones

    def _decide_settle_balance(self):
        """Given the balances of all the leaves figure out actually how to
        settle all the balances. Returns the merge_groups and
        walkers_num_clones

        """

        # initialize the main data structures for specifying how to
        # merge and clone a set of walkers. These will be modified for
        # clones and merges but in the initialized state they will
        # generate all NOTHING records.

        # the merge groups, a list of lists where the elements of the
        # outer list are individual "merge groups" that themselves
        # contain the elements of the walkers that will be squashed in
        # a merge and the index of the merge group in the outer list
        # is the index of the walker that will be kept
        # (i.e. KEEP_MERGE and have its state persist to the next
        # step). Indices appearing in any merge group can themselves
        # not have a merge group
        merge_groups = [[] for i in self.walker_weights]

        # the number of clones to make for each walker. Simply a list
        # of 0 or positive integers that specify how many EXTRA clones
        # will be made. E.g. if a cloned walker is to have 3 children
        # then the number of clones is 2. We consider clones copies
        # from the original walker which is given by the index in the
        # list. This number then gives the number of new slots needed
        # for a cloning event
        walkers_num_clones = [0 for i in self.walker_weights]

        # get all the leaf balances
        leaf_nodes = self.leaf_nodes()
        leaf_balances = [self.node[leaf]['balance'] for leaf in leaf_nodes]

        # get the negative and positive balanced leaves
        neg_leaves = [leaf_nodes[leaf_idx] for leaf_idx in np.argwhere(leaf_balances < 0)]
        pos_leaves = [leaf_nodes[leaf_idx] for leaf_idx in np.argwhere(leaf_balances > 0)]

        # we decide on how the walkers will be cloned and
        # merged. These steps are purely functional and do not modify
        # any attributes on the RegionTree. The merge_groups and
        # walkers_num_clones can be used to commit these changes
        # elsewhere if desired.

        # first do all leaves with negative balances, so that after we
        # have freed up slots we can fill them with clones since in
        # WEXplore we want to have an economy of slots and not create
        # them if we don't have to
        for leaf in neg_leaves:
            merge_groups = self._decide_merge_leaf(leaf, merge_groups)

        # then do all the leaves with positive balances to fill the
        # slots left from squashing walkers
        for leaf in pos_leaves:
            walkers_num_clones = self._decide_clone_leaf(leaf, merge_groups, walkers_num_clones)


        return merge_groups, walkers_num_clones

    def merge_leaf(self, leaf, merge_groups, walkers_num_clones):
        """Actually perform the merges on a leaf."""

        # account for the weight from the squashed walker to
        # the keep walker
        squashed_weight = sum([self.walker_weights[i] for i in squash_walker_idxs])
        self._walker_weights[keep_walker_idx] += squashed_weight
        for squash_idx in squash_walker_idxs:
            self._walker_weights[squash_idx] = 0.0


    def clone_leaf(leaf, merge_groups, walkers_num_clones):
        pass


    def balance_tree(self, max_num_walkers, min_num_walkers, delta_walkers=0):
        """Do balancing between the branches of the tree. the `delta_walkers`
        kwarg can be used to increase or decrease the total number of
        walkers, but defaults to zero which will cause no net change
        in the number of walkers.

        """

        # set the delta walkers to the balance of the root node
        self.node[self.ROOT_NODE]['balance'] = delta_walkers

        # do a breadth first traversal and balance at each level
        for parent, children in nx.bfs_successors(self, self.ROOT_NODE):

            # pass on the balance of this parent to the children from the
            # parents, distribute walkers between
            parental_balance = self.node[parent]['balance']

            # this will both propagate the balance set for the root
            # walker down the tree and balance between the children
            self._propagate_and_balance_shares(parental_balance, children)

        # check that the sum of the balances of the leaf nodes
        # balances to delta_walkers
        leaf_balances = [self.node[leaf]['balance'] for leaf in self.leaf_nodes()]
        if sum(leaf_balances) != delta_walkers:
            raise RegionTreeError(
                "The balances of the leaf nodes ({}) do not balance to delta_walkers ({})".format(
                    leaf_balances, delta_walkers))

        # decide on how to settle all the balances between leaves
        merge_groups, walkers_num_clones = self._decide_settle_balances()

        # count up the number of clones and merges in the merge_groups
        # and the walkers_num_clones
        num_clones = sum(walkers_num_clones)
        num_squashed = sum([len(merge_group) for merge_group in merge_groups])

        # check that the number of clones and number of squashed
        # walkers balance to the delta_walkers amount
        if num_clones - num_squashed != delta_walkers:

            raise RegionTreeError("The number of new clones ({}) is not balanced by the number of"
                                  "squashed walkers ({}) to the delta_walkers specified ({})".format(
                                      num_clones, num_squashed, delta_walkers))


        # now that we have made decisions about which walkers to clone
        # and merge we actually modify the weights of them in the
        # region tree, thus this is a state change (this is not really
        # necessary except for error checking)
        self.settle_balances(merge_groups, walkers_num_clones)


        return merge_groups, walkers_num_clones

class WExploreResampler(Resampler):

    DECISION = MultiCloneMergeDecision

    # datatype for the state change records of the resampler, here
    # that is the defnition of a new branch of the region tree, the
    # value is the level of the tree that is branched. Most of the
    # useful information will be in the auxiliary data, like the
    # image, distance the walker was away from the image at that
    # level, and the id of the leaf node
    RESAMPLER_FIELDS = ('branching_level', 'distance', 'new_leaf_id', 'image')
    RESAMPLER_SHAPES = ((1,), (1,), Ellipsis, Ellipsis)
    RESAMPLER_DTYPES = (np.int, np.float, np.int, None)

    # fields that can be used for a table like representation
    RESAMPLER_RECORD_FIELDS = ('branching_level', 'distance', 'new_leaf_id')

    # fields for resampling data
    RESAMPLING_FIELDS = DECISION.FIELDS + ('step_idx', 'walker_idx', 'region_assignment',)
    RESAMPLING_SHAPES = DECISION.SHAPES + ((1,), (1,), Ellipsis,)
    RESAMPLING_DTYPES = DECISION.DTYPES + (np.int, np.int, np.int,)

    # fields that can be used for a table like representation
    RESAMPLING_RECORD_FIELDS = DECISION.RECORD_FIELDS + \
                               ('step_idx', 'walker_idx', 'region_assignment',)


    def __init__(self, seed=None, pmin=1e-12, pmax=0.1,
                 distance=None,
                 max_n_regions=(10, 10, 10, 10),
                 max_region_sizes=(1, 0.5, 0.35, 0.25),
                 init_state=None,
                ):

        # we call the common methods in the Resampler superclass. We
        # set the min and max number of walkers to be constant
        super().__init__(min_num_walkers=Ellipsis,
                         max_num_walkers=Ellipsis)

        assert distance is not None, "Distance object must be given."
        assert init_state is not None, "An initial state must be given."

        self.decision = self.DECISION

        # the region tree which keeps track of the regions and can be
        # balanced for cloning and merging between them, is
        # initialized the first time resample is called because it
        # needs an initial walker
        self._region_tree = None

        # parameters
        self.pmin=pmin
        self.pmax=pmax
        self.seed = seed
        if self.seed is not None:
            rand.seed(self.seed)

        self.max_n_regions = max_n_regions
        self.n_levels = len(max_n_regions)
        self.max_region_sizes = max_region_sizes # in nanometers!

        # distance metric
        self.distance = distance

        # we do not know the shape and dtype of the images until
        # runtime so we determine them here
        image = self.distance.image(init_state)
        self.image_shape = image.shape
        self.image_dtype = image.dtype


        # initialize the region tree with the first state
        self._region_tree = RegionTree(init_state,
                                       max_n_regions=self.max_n_regions,
                                       max_region_sizes=self.max_region_sizes,
                                       distance=self.distance,
                                       pmin=self.pmin,
                                       pmax=self.pmax)

    def resampler_field_shapes(self):

        # index of the image idx
        image_idx = self.resampler_field_names().index('image')

        # shapes adding the image shape
        shapes = list(super().resampler_field_shapes())
        shapes[image_idx] = self.image_shape

        return tuple(shapes)

    def resampler_field_dtypes(self):

        # index of the image idx
        image_idx = self.resampler_field_names().index('image')

        # dtypes adding the image dtype
        dtypes = list(super().resampler_field_dtypes())
        dtypes[image_idx] = self.image_dtype

        return tuple(dtypes)

    # override the superclass methods to utilize the decision class
    def resampling_field_names(self):
        return self.RESAMPLING_FIELDS

    def resampling_field_shapes(self):
        return self.RESAMPLING_SHAPES

    def resampling_field_dtypes(self):
        return self.RESAMPLING_DTYPES

    def resampling_fields(self):
        return list(zip(self.resampling_field_names(),
                   self.resampling_field_shapes(),
                   self.resampling_field_dtypes()))

    @property
    def region_tree(self):
        return self._region_tree

    def assign(self, walkers, debug_prints=False):
        ## Assign the walkers based on the current defined Voronoi
        ## images which assign them to bins/leaf-nodes, possibly
        ## creating new regions, do this by calling the method to
        ## "place_walkers"  on the tree which changes the tree's state
        new_branches = self.region_tree.place_walkers(walkers)

        # data records about changes to the resampler, here is just
        # the new branches data
        resampler_data = new_branches

        # the assignments
        assignments = np.array(self.region_tree.walker_assignments)

        # return the assignments and the resampler records of changed
        # resampler state, which is addition of new regions
        return assignments, resampler_data

    def decide(self, delta_walkers=0, debug_prints=False):
        """ Make decisions for resampling for a single step. """

        ## Given the assignments (which are on the tree nodes) decide
        ## on which to merge and clone

        # do this by "balancing" the tree. delta_walkers can be
        # specified to increase or decrease the total number of
        # walkers
        merge_groups, walkers_num_clones = \
                        self.region_tree.balance_tree(self.max_num_walkers(),
                                                      self.min_num_walkers(),
                                                      delta_walkers=delta_walkers)



        ## ERROR CHECKING
        if debug_prints:
            print("merge_groups\n{}".format(merge_groups))
            print("Walker number of clones\n{}".format(walkers_num_clones))
            print("Walker assignments\n{}".format(self.region_tree.walker_assignments))
            print("Walker weights\n{}".format(self.region_tree.walker_weights))

        # this is here to check that the walkers in the tree
        # were of valid weights. THis is only necessary if another
        # decision step is going to be made

        # check that there are no walkers violating the pmin and pmax

        # check that all of the weights are less than or equal to the pmax
        assert all([weight <= self.pmax for weight in self.region_tree.walker_weights]), \
            "All walker weights must be less than the pmax"

        # check that all of the weights are greater than or equal to the pmin
        assert all([weight >= self.pmin for weight in self.region_tree.walker_weights]), \
            "All walker weights must be greater than the pmin"

        # check to make sure we have selected appropriate walkers to clone
        # print images
        if debug_prints:
            print("images_assignments\n{}".format(self.region_tree.regions))

        # check that clones are not performed on KEEP_MERGE and SQUASH
        # walkers
        for walker_idx, n_clones in enumerate(walkers_num_clones):

            if n_clones > 0:
                if len(merge_groups[walker_idx]) > 0:
                    raise ValueError("trying to clone a KEEP_MERGE walker")

                squash_idxs = list(it.chain(merge_groups))
                if walker_idx in squash_idxs:
                    raise ValueError("trying to clone a SQUASH walker")

        # DEBUG
        # using the merge groups and the non-specific number of clones
        # for walkers create resampling actions for them (from the
        # Resampler superclass).
        # if sum(walkers_num_clones) > 0:
        #     import ipdb; ipdb.set_trace()

        ## END ERROR CHECKING

        # take the specs for cloning and merging and generate the
        # actual resampling actions (instructions) for each walker,
        # this does not change the state of the resampler or region
        # tree
        resampling_actions = self.assign_clones(merge_groups, walkers_num_clones)

        # check to make sure there are no multiple assignments by
        # keeping track of the taken slots
        taken_slots = []
        for walker_record in resampling_actions:

            # unless it is a squash (which has no slot in the next
            # cycle) add it to the taken slots
            if walker_record['decision_id'] != 3:
                taken_slots.extend(walker_record['target_idxs'])

        if len(set(taken_slots)) < len(taken_slots):
            raise ValueError("Multiple assignments to the same slot")

        # add the walker_idx to the record
        for walker_idx, walker_record in enumerate(resampling_actions):
            walker_record['walker_idx'] = np.array([walker_idx])

        return resampling_actions

    def resample(self, walkers, delta_walkers=0, debug_prints=False):

        # first set how many walkers there are in this resampling
        self._set_resample_num_walkers(len(walkers))

        ## assign/score the walkers, also getting changes in the
        ## resampler state
        assignments, resampler_data = self.assign(walkers)

        if debug_prints:
            print("Assigned regions=\n{}".format(self.region_tree.walker_assignments))

        # make the decisions for the the walkers for only a single
        # step
        resampling_data = self.decide(delta_walkers=delta_walkers,
                                      debug_prints=debug_prints)

        # normally decide is only for a single step and so does not
        # include the step_idx, so we add this to the records
        for walker_idx, walker_record in enumerate(resampling_data):
            walker_record['step_idx'] = np.array([0])

        # convert the target idxs and decision_id to feature vector arrays
        for record in resampling_data:
            record['target_idxs'] = np.array(record['target_idxs'])
            record['decision_id'] = np.array([record['decision_id']])

        # perform the cloning and merging, the action function expects
        # records a lists of lists for steps and walkers
        resampled_walkers = self.DECISION.action(walkers, [resampling_data])

        # check that the weights of the resampled walkers are not
        # beyond the bounds of what they are supposed to be

        # check that all of the weights are less than or equal to the pmax
        assert all([walker.weight <= self.pmax for walker in resampled_walkers]), \
            "All walker weights must be less than the pmax"

        # check that all of the weights are greater than or equal to the pmin
        assert all([walker.weight >= self.pmin for walker in resampled_walkers]), \
            "All walker weights must be less than the pmin"

        # check that the results of the resampling matches what was
        # intended
        # TODO implement this
        pass


        # then add the assignments and distance to image for each walker
        for walker_idx, assignment in enumerate(assignments):
            resampling_data[walker_idx]['region_assignment'] = assignment

        # clear the tree of walker information for the next resampling
        self.region_tree.clear_walkers()

        # unset the number of walkers for this resampling
        self._unset_resampling_num_walkers()

        return resampled_walkers, resampling_data, resampler_data
