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
from typing import Any, List
import torch.fx as fx


def try_get_args(n: fx.Node, args_idx: int, kwargs_str: str, default: Any) -> Any:
    """Look for an argument in a fx.Node. First looks within n.args, then n.kwargs.
    If not found, returns a default.

    :param n: the target node
    :type n: fx.Node
    :param args_idx: the index of the searched arg in the positional arguments
    :type args_idx: int
    :param kwargs_str: the name of the searched arg in the keyword arguments
    :type kwargs_str: str
    :param default: the default value to return in case the searched argument is not found
    :type n: Any
    :return: the searched argument or the default value
    :rtype: Any
    """
    if len(n.args) > args_idx:
        return n.args[args_idx]
    arg = n.kwargs.get(kwargs_str)
    return arg if arg is not None else default


def all_output_nodes(n: fx.Node) -> List[fx.Node]:
    """Return the list of successors for a fx.Node since
    torch.fx does not provide this functionality, but only gives input nodes

    :param n: the target node
    :type n:  fx.Node
    :return: the list of successors
    :rtype: List[fx.Node]
    """
    return list(n.users.keys())
