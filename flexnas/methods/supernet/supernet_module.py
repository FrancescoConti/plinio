
from typing import Iterable, Iterator, Tuple
import torch
import torch.nn as nn
from torchinfo import summary


class SuperNetModule(nn.Module):
    """A nn.Module containing some layers among which the SuperNet NAS tool
    will choose the one that is more suitable

    :param nn: _description_
    :type nn: _type_
    """
    def __init__(self, input_layers: Iterable[nn.Module]):
        super(SuperNetModule, self).__init__()

        self.input_layers = nn.ModuleList(list(input_layers))
        self.input_shape = None
        self.n_layers = len(self.input_layers)
        self.layers_sizes = []
        self.layers_macs = []

        self.alpha = nn.Parameter(
            (1 / self.n_layers) * torch.ones(self.n_layers, dtype=torch.float), requires_grad=True)

    def compute_layers_sizes(self):
        """Computes the size of each possible layer of the SuperNetModule
        and stores the values in a list
        """
        for layer in self.input_layers:
            layer_size = 0
            for param in layer.parameters():
                layer_size += torch.prod(torch.tensor(param.shape))
            self.layers_sizes.append(layer_size)

    def compute_layers_macs(self):
        """Computes the number of macs of each possible layer of the SuperNetModule
        and stores the values in a list
        """
        for layer in self.input_layers:
            stats = summary(layer, self.input_shape, verbose=0, mode='eval')
            self.layers_macs.append(stats.total_mult_adds)

    def forward(self, input: torch.Tensor) -> torch.Tensor:
        """Forward function for the SuperNetModule that returns a weighted
        sum of all the outputs of the different input layers.

        :param input: the input tensor
        :type input: torch.Tensor
        :return: the output tensor (weighted sum of all layers output)
        :rtype: torch.Tensor
        """
        soft_alpha = nn.functional.softmax(self.alpha, dim=0)

        y = []
        for i, layer in enumerate(self.input_layers):
            y.append(soft_alpha[i] * layer(input))
        y = torch.stack(y, dim=0).sum(dim=0)
        return y

    def export(self) -> nn.Module:
        """It returns a single layer within the ones
        given as input parameter to the SuperNetModule.
        The chosen layer will be the one with the highest alpha value (highest probability).

        :return: single nn layer
        :rtype: nn.Module
        """
        index = torch.argmax(self.alpha).item()
        return self.input_layers[int(index)]

    def get_size(self) -> torch.Tensor:
        """Method that returns the number of weights for the module
        computed as a weighted sum of the number of weights of each layer.

        :return: number of weights of the module (weighted sum)
        :rtype: torch.Tensor
        """
        soft_alpha = nn.functional.softmax(self.alpha, dim=0)

        size = torch.tensor(0, dtype=torch.float32)
        for i in range(self.n_layers):
            size = size + (soft_alpha[i] * self.layers_sizes[i])
        return size

    def get_macs(self) -> torch.Tensor:
        """Method that computes the number of MAC operations for the module

        :return: the number of MACs
        :rtype: torch.Tensor
        """
        soft_alpha = nn.functional.softmax(self.alpha, dim=0)

        macs = torch.tensor(0, dtype=torch.float32)
        for i in range(self.n_layers):
            macs = macs + (soft_alpha[i] * self.layers_macs[i])
        return macs

    def named_nas_parameters(
            self, prefix: str = '', recurse: bool = False) -> Iterator[Tuple[str, nn.Parameter]]:
        """Returns an iterator over the architectural parameters of this module, yielding
        both the name of the parameter as well as the parameter itself

        :param prefix: prefix to prepend to all parameter names, defaults to ''
        :type prefix: str, optional
        :param recurse: kept for uniformity with pytorch API, defaults to False
        :type recurse: bool, optional
        :yield: an iterator over the architectural parameters of all layers of the module
        :rtype: Iterator[Tuple[str, nn.Parameter]]
        """
        prfx = prefix
        prfx += "." if len(prefix) > 0 else ""
        prfx += "alpha"
        yield prfx, self.alpha

    def nas_parameters(self, recurse: bool = False) -> Iterator[nn.Parameter]:
        """Returns an iterator over the architectural parameters of this module

        :param recurse: kept for uniformity with pytorch API, defaults to False
        :type recurse: bool, optional
        :yield: an iterator over the architectural parameters of all layers of the module
        :rtype: Iterator[nn.Parameter]
        """
        for _, param in self.named_nas_parameters(recurse=recurse):
            yield param

    def __getitem__(self, pos: int) -> nn.Module:
        """Get the layer at position pos in the list of all the possible
        layers for the SuperNetModule

        :param pos: position of the required layer in the list input_layers
        :type pos: int
        :return: layer at postion pos in the list input_layers
        :rtype: nn.Module
        """
        return self.input_layers[pos]
