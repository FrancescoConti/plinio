# *----------------------------------------------------------------------------*
# * Copyright (C) 2021 Politecnico di Torino, Italy                            *
# * SPDX-License-Identifier: Apache-2.0                                        *
# *                                                                            *
# * Licensed under the Apache License, Version 2.0 (the "License");            *
# * you may not use this file except in compliance with the License.           *
# * You may obtain a copy of the License at                                    *
# *                                                                            *
# * http://www.apache.org/licenses/LICENSE-2.0                                 *
# *                                                                            *
# * Unless required by applicable law or agreed to in writing, software        *
# * distributed under the License is distributed on an "AS IS" BASIS,          *
# * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.   *
# * See the License for the specific language governing permissions and        *
# * limitations under the License.                                             *
# *                                                                            *
# * Author:  Daniele Jahier Pagliari <daniele.jahier@polito.it>                *
# *----------------------------------------------------------------------------*
from typing import List, Type
import operator
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.fx as fx
import networkx as nx


def fx_to_nx_graph(fx_graph: fx.Graph) -> nx.DiGraph:
    """Transforms a `torch.fx.Graph` into an equivalent `networkx.DiGraph` for easier visits.

    :param fx_graph: the `torch.fx.Graph` instance.
    :type fx_graph: fx.Graph
    :return: the corresponding `networkx.DiGraph`
    :rtype: nx.DiGraph
    """
    nx_graph = nx.DiGraph()
    for n in fx_graph.nodes:
        for i in n.all_input_nodes:
            nx_graph.add_edge(i, n)
    return nx_graph


def get_input_nodes(fx_graph: fx.Graph) -> List[fx.Node]:
    """From a `torch.fx.Graph`, return the list of nodes that correspond to network inputs.

    Basically finds all nodes of type 'placeholder'.

    :param fx_graph: the network graph
    :type fx_graph: fx.Graph
    :return: a list of `torch.fx.Node` instances corresponding to network inputs.
    :rtype: List[fx.Node]
    """
    ret = []
    for n in fx_graph.nodes:
        if n.op == 'placeholder':
            ret.append(n)
    return ret


def get_output_nodes(fx_graph: fx.Graph) -> List[fx.Node]:
    """From a `torch.fx.Graph`, return the list of nodes that correspond to network outputs.

    Basically finds all nodes of type 'output'.

    :param fx_graph: the network graph
    :type fx_graph: fx.Graph
    :return: a list of `torch.fx.Node` instances corresponding to network outputs.
    :rtype: List[fx.Node]
    """
    ret = []
    for n in fx_graph.nodes:
        if n.op == 'output':
            ret.append(n)
    return ret


def is_layer(n: fx.Node, parent: fx.GraphModule, layer: Type[nn.Module]) -> bool:
    """Checks if a `torch.fx.Node` corresponds to a specific layer type.

    :param n: the target node
    :type n: fx.Node
    :param parent: the parent `nn.Module`
    :type parent: fx.GraphModule
    :param layer: the layer type to be checked
    :type layer: Type[nn.Module]
    :return: `True` if `n` is of type `layer`
    :rtype: bool
    """
    if n.op != 'call_module':
        return False
    return type(parent.get_submodule(str(n.target))) == layer


def is_zero_or_one_input_op(n: fx.Node) -> bool:
    """Checks if a `torch.fx.Node` has no more than 1 input.

    :param n: the target node
    :type n: fx.Node
    :return: `True` if `n` has 0 or 1 inputs.
    :rtype: bool
    """
    return len(n.all_input_nodes) <= 1


def is_shared_input_features_op(n: fx.Node, parent: fx.GraphModule) -> bool:
    """Checks if a `torch.fx.Node` corresponds to an operation that requires all its inputs to
    share the same number of features.

    Note that this is implemented as a simple pattern matching against a (non-exhaustive) list of
    `torch.fx` ops.

    :param n: the target node
    :type n: fx.Node
    :param parent: the parent sub-module
    :type parent: fx.GraphModule
    :return: `True` if `n` requires all its inputs to have the same number of features.
    :rtype: bool
    """
    if is_zero_or_one_input_op(n):
        return False
    if n.op == 'call_function':
        if n.target == torch.add:
            return True
        if n.target == operator.add:
            return True
        if n.target == torch.sub:
            return True
        if n.target == operator.sub:
            return True
        # TODO: add others here
    # are there any modules that require same input size? if so, add them below. Same for methods
    # if n.op == 'call_module':
    # if n.op == 'call_method':
    return False


def is_features_defining_op(n: fx.Node, parent: fx.GraphModule) -> bool:
    """Checks if a `torch.fx.Node` corresponds to an operation that "defines" the number of
    features for successors.

    For example, convolutions and fully-connected layers have, in general,
    out_features != in_features, hence they are "features-defining". In contrast, ReLU has
    out_features == in_features, hence it is "features-propagating".

    Note that this is implemented as a simple pattern matching against a (non-exhaustive) list of
    `torch.fx` ops.

    :param n: the target node
    :type n: fx.Node
    :param parent: the parent sub-module
    :type parent: fx.GraphModule
    :return: `True` if `n` corresponds to a "features-defining" op.
    :rtype: bool
    """
    if n.op == 'placeholder' and len(n.all_input_nodes) == 0:  # input node
        return True
    if n.op == 'call_module':
        submodule = parent.get_submodule(str(n.target))
        if type(submodule) == nn.Conv1d:
            return True
        if type(submodule) == nn.Conv2d:
            return True
        if type(submodule) == nn.Linear:
            return True
    return False


def is_features_propagating_op(n: fx.Node, parent: fx.GraphModule) -> bool:
    """Checks if a `torch.fx.Node` corresponds to an operation that "propagates" the number of
    input features to successors.

    For example, convolutions and fully-connected layers have, in general,
    out_features != in_features, hence they are "features-defining". In contrast, ReLU has
    out_features == in_features, hence it is "features-propagating".

    Note that this is implemented as a simple pattern matching against a (non-exhaustive) list of
    `torch.fx` ops.

    :param n: the target node
    :type n: fx.Node
    :param parent: the parent sub-module
    :type parent: fx.GraphModule
    :return: `True` if `n` corresponds to a "features-propagating" op.
    :rtype: bool
    """
    if n.op == 'output':
        return True
    if n.op == 'call_module':
        submodule = parent.get_submodule(str(n.target))
        if type(submodule) == nn.BatchNorm1d:
            return True
        if type(submodule) == nn.BatchNorm2d:
            return True
        if type(submodule) == nn.AvgPool1d:
            return True
        if type(submodule) == nn.AvgPool2d:
            return True
        if type(submodule) == nn.MaxPool1d:
            return True
        if type(submodule) == nn.BatchNorm2d:
            return True
        if type(submodule) == nn.Dropout:
            return True
        if type(submodule) == nn.ReLU:
            return True
        if type(submodule) == nn.ReLU6:
            return True
        if type(submodule) == nn.ConstantPad1d:
            return True
        if type(submodule) == nn.ConstantPad2d:
            return True
        # TODO: add others
    if n.op == 'call_function':
        if n.target == F.relu:
            return True
        if n.target == F.relu6:
            return True
        if n.target == F.log_softmax:
            return True
    return False


def is_flatten(n: fx.Node, parent: fx.GraphModule) -> bool:
    """Checks if a `torch.fx.Node` instance corresponds to a flatten operation.

    :param n: the target node
    :type n: fx.Node
    :param parent: the parent sub-module
    :type parent: fx.GraphModule
    :return: `True` if `n` corresponds to a flatten op.
    :rtype: bool
    """
    if n.op == 'call_method' and n.target == 'flatten':
        return True
    if n.op == 'call_function' and n.target == torch.flatten:
        return True
    return False


def is_concatenate(n: fx.Node, parent: fx.GraphModule) -> bool:
    """Checks if a `torch.fx.Node` instance corresponds to a concat operation.

    :param n: the target node
    :type n: fx.Node
    :param parent: the parent sub-module
    :type parent: fx.GraphModule
    :return: `True` if `n` corresponds to a concat op.
    :rtype: bool
    """
    if n.op == 'call_function' and n.target == torch.cat:
        return True
    return False
