
from typing import cast, Tuple, Iterable, List, Any, Iterator, Dict
import torch
import torch.nn as nn
import torch.fx as fx
from torch.fx.passes.shape_prop import ShapeProp
from flexnas.methods.dnas_base import DNAS
from flexnas.methods.supernet.supernet_module import SuperNetModule


class SuperNetTracer(fx.Tracer):
    def __init__(self) -> None:
        super().__init__()  # type: ignore

    def is_leaf_module(self, m: torch.nn.Module, module_qualified_name: str) -> bool:
        if isinstance(m, SuperNetModule):
            return True
        else:
            return m.__module__.startswith('torch.nn') and not isinstance(m, torch.nn.Sequential)


class SuperNet(DNAS):
    """A class that wraps a nn.Module with the functionality of the SuperNet NAS tool

    :param model: the inner nn.Module instance optimized by the NAS
    :type model: nn.Module
    :param input_shape: the shape of an input tensor, without batch size, required for symbolic
    tracing
    :type input_shape: Tuple[int, ...]
    :param regularizer: a string defining the type of cost regularizer, defaults to 'size'
    :type regularizer: Optional[str], optional
    :param exclude_names: the names of `model` submodules that should be ignored by the NAS
    when auto-converting layers, defaults to ()
    :type exclude_names: Iterable[str], optional
    """
    def __init__(
            self,
            model: nn.Module,
            input_shape: Tuple[int, ...],
            regularizer: str = 'size',
            exclude_names: Iterable[str] = ()):

        super(SuperNet, self).__init__(regularizer, exclude_names)

        self._input_shape = input_shape
        self._regularizer = regularizer
        self.seed = model
        self.exclude_names = exclude_names

        target_modules = []
        self._target_modules = self.get_supernetModules(target_modules, model, exclude_names)

        tracer = SuperNetTracer()
        graph = tracer.trace(model.eval())
        name = model.__class__.__name__
        mod = fx.GraphModule(tracer.root, graph, name)
        # create a "fake" minibatch of 1 inputs for shape prop
        batch_example = torch.stack([torch.rand(self._input_shape)] * 1, 0)
        # TODO: this is not very robust. Find a better way
        device = next(model.parameters()).device
        ShapeProp(mod).propagate(batch_example.to(device))

        self.compute_shapes(mod)

    def get_supernetModules(
            self,
            target_modules: List,
            model: nn.Module,
            exclude_names: Iterable[str]) -> List[Tuple[str, SuperNetModule]]:
        """This function spots each SuperNetModule contained in the model received
        and saves them in a list.

        :param target_modules: list where the function saves the SuperNetModules
        :type target_modules: List
        :param model: seed model
        :type model: nn.Module
        :param exclude_names: the names of `model` submodules that should be ignored by the NAS
        :type exclude_names: Iterable[str]
        :return: list of target modules for the NAS
        :rtype: List[Tuple[str, SuperNetModule]]
        """
        for named_module in model.named_modules():
            if (named_module[0] != ''):
                submodules = list(named_module[1].children())
                if (named_module[1].__class__.__name__ == "SuperNetModule"):
                    if (named_module[0] not in exclude_names):
                        target_modules.append(named_module)
                elif (submodules):
                    for child in submodules:
                        self.get_supernetModules(target_modules, child, exclude_names)
        return target_modules

    def compute_shapes(self, mod: fx.GraphModule):
        """This function computes the input shape for each SuperNetModule in the target modules
        """
        if (self._target_modules):
            g = mod.graph

            for t in self._target_modules:
                for n in g.nodes:
                    if t[0] == n.target:
                        t[1].input_shape = n.all_input_nodes[0].meta['tensor_meta'].shape

            for target in self._target_modules:
                target[1].compute_layers_sizes()
                target[1].compute_layers_macs()

    def forward(self, *args: Any) -> torch.Tensor:
        """Forward function for the DNAS model. Simply invokes the inner model's forward

        :return: the output tensor
        :rtype: torch.Tensor
        """
        return self.seed.forward(*args)

    def supported_regularizers(self) -> Tuple[str, ...]:
        """Returns a list of names of supported regularizers

        :return: a tuple of strings with the name of supported regularizers
        :rtype: Tuple[str, ...]
        """
        return ('size', 'macs')

    def get_size(self) -> torch.Tensor:
        """Computes the total number of parameters of all NAS-able modules

        :return: the total number of parameters
        :rtype: torch.Tensor
        """
        size = torch.tensor(0, dtype=torch.float32)
        for module in self._target_modules:
            size = size + module[1].get_size()
        return size

    def get_macs(self) -> torch.Tensor:
        """Computes the total number of MACs in all NAS-able modules

        :return: the total number of MACs
        :rtype: torch.Tensor
        """
        macs = torch.tensor(0, dtype=torch.float32)
        for t in self._target_modules:
            macs = macs + t[1].get_macs()
        return macs

    @property
    def regularizer(self) -> str:
        """Returns the regularizer type

        :raises ValueError: for unsupported conversion types
        :return: the string identifying the regularizer type
        :rtype: str
        """
        return self._regularizer

    @regularizer.setter
    def regularizer(self, value: str):
        if value == 'size':
            self.get_regularization_loss = self.get_size
        elif value == 'macs':
            self.get_regularization_loss = self.get_macs
        else:
            raise ValueError(f"Invalid regularizer {value}")
        self._regularizer = value

    def arch_export(self) -> nn.Module:
        """Export the architecture found by the NAS as a 'nn.Module'
        It replaces each SuperNetModule found in the model with a single layer.

        :return: the architecture found by the NAS
        :rtype: nn.Module
        """
        model = self.seed

        for module in self._target_modules:
            submodule = cast(SuperNetModule, model.get_submodule(module[0]))
            module_exp = submodule.export()

            path = module[0].split('.')
            if (len(path) > 1):
                parent = model.get_submodule(path[-2])
            else:
                parent = model

            parent.add_module(path[-1], module_exp)

        return model

    def arch_summary(self) -> Dict[str, str]:
        """Generates a dictionary representation of the architecture found by the NAS.
        Only optimized layers are reported

        :return: a dictionary representation of the architecture found by the NAS
        :rtype: Dict[str, Dict[str, Any]]
        """
        arch = {}

        for module in self._target_modules:
            mod = module[1].export()
            name = mod.__class__.__name__
            if (name == "Conv2d" or name == "Conv1d"):
                kernel_size = mod.kernel_size
                t = (name, kernel_size)
                arch[module[0]] = t
            else:
                arch[module[0]] = name
        return arch

    def named_nas_parameters(
            self, prefix: str = '', recurse: bool = False) -> Iterator[Tuple[str, nn.Parameter]]:
        """Returns an iterator over the architectural parameters of the NAS, yielding
        both the name of the parameter as well as the parameter itself

        :param prefix: prefix to prepend to all parameter names.
        :type prefix: str
        :param recurse: kept for uniformity with pytorch API
        :type recurse: bool
        :return: an iterator over the architectural parameters of the NAS
        :rtype: Iterator[nn.Parameter]
        """
        for module in self._target_modules:
            prfx = prefix
            prfx += "." if len(prefix) > 0 else ""
            prfx += module[0]
            prfx += "." if len(prfx) > 0 else ""
            for name, param in module[1].named_nas_parameters():
                prfx = prfx + name
                yield prfx, param

    def named_net_parameters(
            self, prefix: str = '', recurse: bool = True) -> Iterator[Tuple[str, nn.Parameter]]:
        """Returns an iterator over the inner network parameters, EXCEPT the NAS architectural
        parameters, yielding both the name of the parameter as well as the parameter itself

        :param prefix: prefix to prepend to all parameter names.
        :type prefix: str
        :param recurse: kept for uniformity with pytorch API, not actually used
        :type recurse: bool
        :return: an iterator over the inner network parameters
        :rtype: Iterator[nn.Parameter]
        """
        exclude = set(_[0] for _ in self.named_nas_parameters())

        for name, param in self.seed.named_parameters():
            if name not in exclude:
                yield name, param

    def __str__(self):
        """Prints the architecture found by the NAS to screen

        :return: a str representation of the current architecture
        :rtype: str
        """
        arch = self.arch_summary()
        return str(arch)
