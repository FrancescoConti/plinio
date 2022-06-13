# *----------------------------------------------------------------------------*
# * Copyright (C) 2022 Politecnico di Torino, Italy                            *
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
from typing import Iterable, Tuple, Type
import unittest
import torch
import torch.nn as nn
from flexnas.methods import DNAS, PIT
from flexnas.methods.pit import PITConv1d, pit_conv1d
from unit_test.models import SimpleNN
from unit_test.models import TCResNet14
from unit_test.models import SimplePitNN
from unit_test.models import ToyModel1, ToyModel2, ToyModel3, ToyModel4, ToyModel5
from torch.nn.parameter import Parameter
from pytorch_model_summary import summary
import numpy as np


class TestPIT(unittest.TestCase):
    """PIT NAS testing class.

    TODO: could be separated in more sub-classes, creating a test_pit folder with test_convert/
    test_extract/ etc subfolders.
    """

    def setUp(self):
        self.config = {
            "input_channels": 6,
            "output_size": 12,
            "num_channels": [24, 36, 36, 48, 48, 72, 72],
            "kernel_size": 9,
            "dropout": 0.5,
            "grad_clip": -1,
            "use_bias": True,
            "avg_pool": True,
        }

    def test_prepare_simple_model(self):
        """Test the conversion of a simple sequential model"""
        nn_ut = SimpleNN()
        new_nn = self._execute_prepare(nn_ut, input_example=torch.rand((1, 3, 40)))
        self._compare_prepared(nn_ut, new_nn._inner_model, nn_ut, new_nn)
        # Number of NAS-able layers check
        n_tgt = len(new_nn._target_layers)
        exp_tgt = 2
        self.assertEqual(exp_tgt, n_tgt,
                         "SimpleNN has {} conv layers, but found {} target layers".format(
                             exp_tgt, n_tgt))

        # print(summary(nn_ut, torch.rand((1, 3, 40)), show_input=False, show_hierarchical=True))

        # print("")
        # print("Converted inner model")
        # print(new_nn._inner_model)

        # Input features check on the NAS-able layers
        conv0_input = new_nn._inner_model.conv0.input_features_calculator.features  # type: ignore
        conv0_exp_input = 3
        self.assertEqual(conv0_exp_input, conv0_input,
                         "Conv0 has {} input features, but found {}".format(
                             conv0_exp_input, conv0_input))
        conv1_input = new_nn._inner_model.conv1\
                            .input_features_calculator.features.item()  # type: ignore
        conv1_exp_input = 32
        self.assertEqual(conv1_exp_input, conv1_input,
                         "Conv1 has {} input features, but found {}".format(
                             conv1_exp_input, conv1_input))

    # def test_convert_pit_model(self):
    #     new_pit_model = self._execute_prepare(self.new_nn, input_example=torch.rand((1, 3, 40)))
    #     print("")
    #     print("Converted pit model inner model")
    #     print(new_pit_model)

    def test_toy_model1(self):
        """Test PIT fucntionalities on ToyModel1"""
        nn_ut = ToyModel1()
        new_nn = self._execute_prepare(nn_ut, input_example=torch.rand((1, 3, 15)))

        # Input features check
        conv2_exp_input = 3
        conv2_input = new_nn._inner_model.conv2\
                            .input_features_calculator.features  # type: ignore
        self.assertEqual(conv2_exp_input, conv2_input,
                         "Conv2 has {} input features, but found {}".format(
                             conv2_exp_input, conv2_input))
        conv5_exp_input = 64
        conv5_input = new_nn._inner_model.conv5\
                            .input_features_calculator.features  # type: ignore
        self.assertEqual(conv5_exp_input, conv5_input,
                         "Conv5 has {} input features, but found {}".format(
                             conv5_exp_input, conv5_input))
        conv4_exp_input = 50
        conv4_input = new_nn._inner_model.conv4\
                            .input_features_calculator.features  # type: ignore
        self.assertEqual(conv4_exp_input, conv4_input,
                         "Conv4 has {} input features, but found {}".format(
                             conv4_exp_input, conv4_input))

        # Input shared masker check
        conv5_alpha = new_nn._inner_model.\
            conv5.out_channel_masker.alpha.detach().numpy()  # type: ignore
        conv4_alpha = new_nn._inner_model.\
            conv4.out_channel_masker.alpha.detach().numpy()  # type: ignore
        conv3_alpha = new_nn._inner_model.\
            conv3.out_channel_masker.alpha.detach().numpy()  # type: ignore
        conv2_alpha = new_nn._inner_model.\
            conv2.out_channel_masker.alpha.detach().numpy()  # type: ignore
        conv1_alpha = new_nn._inner_model.\
            conv1.out_channel_masker.alpha.detach().numpy()  # type: ignore
        conv0_alpha = new_nn._inner_model.\
            conv0.out_channel_masker.alpha.detach().numpy()  # type: ignore

        # Two convolutional layers must have the same shared masker before a concat
        masker_alpha_conv_0_1 = np.array_equal(conv0_alpha, conv1_alpha)  # type: ignore
        self.assertTrue(masker_alpha_conv_0_1)

        # The convolutional layer after the add operation must have a different one
        masker_alpha_conv_0_5 = np.array_equal(conv0_alpha, conv5_alpha)  # type: ignore
        self.assertFalse(masker_alpha_conv_0_5)

        # Two consecutive convolutional layers with different out channels must have
        # different shared masker associated
        masker_alpha_conv_3_4 = np.array_equal(conv3_alpha, conv4_alpha)  # type: ignore
        self.assertFalse(masker_alpha_conv_3_4)

        # Three convolutional layers before and add must have the same shared masker
        masker_alpha_conv_2_4 = np.array_equal(conv2_alpha, conv4_alpha)  # type: ignore
        masker_alpha_conv_4_5 = np.array_equal(conv4_alpha, conv5_alpha)  # type: ignore
        self.assertTrue(masker_alpha_conv_2_4)
        self.assertTrue(masker_alpha_conv_4_5)

        # Exclude types check
        nn_ut = ToyModel1()
        new_nn = self._execute_prepare(nn_ut, input_example=torch.rand((1, 3, 15)),
                                       exclude_types=[nn.Conv1d])  # type: ignore
        n_tgt = len(new_nn._target_layers)
        exp_tgt = 0
        self.assertEqual(exp_tgt, n_tgt,
                         "ToyModel1 (excluding the nn.Conv1d type) has {} NAS-able layers,\
                          but found {} target layers".format(exp_tgt, n_tgt))

        # Exclude names check
        nn_ut = ToyModel1()
        new_nn = self._execute_prepare(nn_ut, input_example=torch.rand((1, 3, 15)),
                                       exclude_names=['conv0', 'conv4'])  # type: ignore
        n_tgt = len(new_nn._target_layers)
        exp_tgt = 4
        self.assertEqual(exp_tgt, n_tgt,
                         "ToyModel1 (excluding conv0 and conv4) has {} NAS-able layers,\
                          but found {} target layers".format(exp_tgt, n_tgt))
        # I must not find a PITChannelMasker corresponding to the excluded layer
        conv4_masker = True
        try:
            new_nn._inner_model.conv4.out_channel_masker.alpha.detach().numpy()  # type: ignore
        except Exception:
            conv4_masker = False
        self.assertFalse(conv4_masker)

    def test_toy_model2(self):
        """Test PIT fucntionalities on ToyModel2"""
        nn_ut = ToyModel2()
        new_nn = self._execute_prepare(nn_ut, input_example=torch.rand((1, 3, 60)))
        # print(summary(nn_ut, torch.rand((1, 3, 60)), show_input=True, show_hierarchical=False))
        # print(summary(nn_ut, torch.rand((1, 3, 60)), show_input=False, show_hierarchical=True))
        # print(new_nn._inner_model)

        # Input features check
        conv2_exp_input = 3
        conv2_input = new_nn._inner_model.conv2\
                            .input_features_calculator.features  # type: ignore
        self.assertEqual(conv2_exp_input, conv2_input,
                         "Conv2 has {} input features, but found {}".format(
                             conv2_exp_input, conv2_input))
        conv4_exp_input = 40
        conv4_input = new_nn._inner_model.conv4\
                            .input_features_calculator.features  # type: ignore
        self.assertEqual(conv4_exp_input, conv4_input,
                         "Conv4 has {} input features, but found {}".format(
                             conv4_exp_input, conv4_input))

        # Input shared masker check
        conv1_alpha = new_nn._inner_model.\
            conv1.out_channel_masker.alpha.detach().numpy()  # type: ignore
        conv0_alpha = new_nn._inner_model.\
            conv0.out_channel_masker.alpha.detach().numpy()  # type: ignore

        # Two convolutional layers must have the same shared masker before a concat
        masker_alpha_conv_0_1 = np.array_equal(conv0_alpha, conv1_alpha)  # type: ignore
        self.assertTrue(masker_alpha_conv_0_1)

        # Exclude names check
        nn_ut = ToyModel2()
        new_nn = self._execute_prepare(nn_ut, input_example=torch.rand((1, 3, 60)),
                                       exclude_names=['conv0', 'conv4'])  # type: ignore
        n_tgt = len(new_nn._target_layers)
        exp_tgt = 3
        self.assertEqual(exp_tgt, n_tgt,
                         "ToyModel2 (excluding conv0 and conv4) has {} NAS-able layers,\
                          but found {} target layers".format(exp_tgt, n_tgt))

        # I must not find a PITChannelMasker corresponding to the excluded layer
        conv4_masker = True
        try:
            new_nn._inner_model.conv4.out_channel_masker.alpha.detach().numpy()  # type: ignore
        except Exception:
            conv4_masker = False
        self.assertFalse(conv4_masker)

        # Test autoconvert set to False
        nn_ut = ToyModel2()
        new_nn = self._execute_prepare(nn_ut, input_example=torch.rand((1, 3, 60)),
                                       autoconvert_layers=False)
        self._compare_prepared(nn_ut, new_nn._inner_model, nn_ut, new_nn, autoconvert_layers=False)
        n_tgt = len(new_nn._target_layers)
        exp_tgt = 0
        self.assertEqual(exp_tgt, n_tgt,
                         "SimpleNN (excluding the nn.Conv1d type) has {} NAS-able layers,\
                          but found {} target layers".format(exp_tgt, n_tgt))

    def test_exclude_names(self):
        """Test the exclude_names functionality"""
        nn_ut = SimpleNN()
        new_nn = self._execute_prepare(nn_ut, input_example=torch.rand((1, 3, 40)),
                                       exclude_names=['conv0'])
        n_tgt = len(new_nn._target_layers)
        exp_tgt = 1
        self.assertEqual(exp_tgt, n_tgt,
                         "SimpleNN (excluding conv0) has {} NAS-able layers , \
                             but found {} target layers".format(exp_tgt, n_tgt))
        new_nn = self._execute_prepare(nn_ut, input_example=torch.rand((1, 3, 40)),
                                       exclude_names=['conv0', 'conv1'])
        n_tgt = len(new_nn._target_layers)
        exp_tgt = 0
        self.assertEqual(exp_tgt, n_tgt,
                         "SimpleNN (excluding conv0 and conv1) has {} NAS-able layers, \
                          but found {} target layers".format(exp_tgt, n_tgt))
        nn_ut = TCResNet14(self.config)
        new_nn = self._execute_prepare(nn_ut, input_example=torch.rand((1, 6, 50)),
                                       exclude_names=['conv0', 'tcn_network_5_tcn1',
                                       'tcn_network_3_tcn0', 'tcn_network_2_batchnorm1'])
        n_tgt = len(new_nn._target_layers)
        exp_tgt = 16
        self.assertEqual(exp_tgt, n_tgt,
                         "TCResNet14 (excluding 3 conv layers) has {} NAS-able layers, \
                          but found {} target layers".format(exp_tgt, n_tgt))

    def test_exclude_types(self):
        """Test the exclude_types functionality"""
        nn_ut = SimpleNN()
        new_nn = self._execute_prepare(nn_ut, input_example=torch.rand((1, 3, 40)),
                                       exclude_types=[nn.Conv1d])  # type: ignore
        n_tgt = len(new_nn._target_layers)
        exp_tgt = 0
        self.assertEqual(exp_tgt, n_tgt,
                         "SimpleNN (excluding the nn.Conv1d type) has {} NAS-able layers,\
                          but found {} target layers".format(exp_tgt, n_tgt))

        nn_ut = TCResNet14(self.config)
        new_nn = self._execute_prepare(nn_ut, input_example=torch.rand((1, 6, 50)),
                                       exclude_types=[nn.Conv1d])  # type: ignore
        n_tgt = len(new_nn._target_layers)
        exp_tgt = 0
        self.assertEqual(exp_tgt, n_tgt,
                         "SimpleNN (excluding the nn.Conv1d type) has {} NAS-able layers,\
                          but found {} target layers".format(exp_tgt, n_tgt))

        # print("")
        # print("Converted resnet inner model")
        # print(new_nn._inner_model)

    def test_prepare_tc_resnet_14(self):
        """Test the conversion of a ResNet-like model"""
        nn_ut = TCResNet14(self.config)
        new_nn = self._execute_prepare(nn_ut, input_example=torch.rand((1, 6, 50)))
        self._compare_prepared(nn_ut, new_nn._inner_model, nn_ut, new_nn)

        # Number of NAS-able layers check
        n_tgt = len(new_nn._target_layers)
        exp_tgt = 3 * len(self.config['num_channels'][1:]) + 1
        self.assertEqual(exp_tgt, n_tgt,
                         "TCResNet14 has {} conv layers, but found {} target layers".format(
                             exp_tgt, n_tgt))
        # print("")
        # print("Original resnet inner model")
        # print(summary(nn_ut, torch.rand((1, 6, 50)), show_input=True))
        # print(summary(nn_ut, torch.rand((1, 6, 50)), show_input=False))
        # print(summary(nn_ut, torch.rand((1, 6, 50)), show_input=True, show_hierarchical=True))

        converted_layers_name = dict(new_nn._inner_model.named_modules())
        # print(converted_layers_name.keys())

        # Input features check on the NAS-able layers
        conv0_input = new_nn._inner_model\
                            .conv0.input_features_calculator.features  # type: ignore
        conv0_exp_input = 6
        self.assertEqual(conv0_exp_input, conv0_input,
                         "Conv0 has {} input features, but found {}".format(
                             conv0_exp_input, conv0_input))

        tcn_network_0_tcn0_exp_input = 24
        tcn_network_0_tcn0_input = \
            converted_layers_name['tcn.network.0.tcn0'].input_features_calculator.features.item()  # type: ignore
        self.assertEqual(tcn_network_0_tcn0_exp_input, tcn_network_0_tcn0_input,
                         "tcn.network.0.tcn0 has {} input features, but found {}".format(
                             tcn_network_0_tcn0_exp_input, tcn_network_0_tcn0_input))

        tcn_network_2_downsample_exp_input = 36
        tcn_network_2_downsample_input = \
            converted_layers_name['tcn.network.2.downsample'].input_features_calculator.features  # type: ignore
        self.assertEqual(tcn_network_2_downsample_exp_input, tcn_network_2_downsample_input,
                         "tcn.network.2.downsample has {} input features, but found {}".format(
                             tcn_network_2_downsample_exp_input, tcn_network_2_downsample_input))

        tcn_network_5_tcn1_exp_input = 72
        tcn_network_5_tcn1_input = \
            converted_layers_name['tcn.network.5.tcn1'].input_features_calculator.features  # type: ignore
        self.assertEqual(tcn_network_5_tcn1_exp_input, tcn_network_5_tcn1_input,
                         "tcn.network.5.tcn1 has {} input features, but found {}".format(
                             tcn_network_5_tcn1_exp_input, tcn_network_5_tcn1_input))

    def test_prepare_simple_pit_model(self):
        """Test the conversion of a simple sequential model already containing a pit layer"""
        nn_ut = SimplePitNN()
        # print("")
        # print("inner model")
        # print(summary(nn_ut, torch.rand((1, 3, 40)), show_input=True, show_hierarchical=True))
        new_nn = self._execute_prepare(nn_ut, input_example=torch.rand((1, 3, 40)))
        self._compare_prepared(nn_ut, new_nn._inner_model, nn_ut, new_nn)
        # Check with autoconvert disabled
        new_nn = self._execute_prepare(nn_ut, input_example=torch.rand((1, 3, 40)),
                                       autoconvert_layers=False)
        self._compare_prepared(nn_ut, new_nn._inner_model, nn_ut, new_nn, autoconvert_layers=False)
        # print("")
        # print("Converted resnet inner model")
        # print(new_nn._inner_model)

    def test_custom_channel_masking(self):
        """Test a pit layer output with a custom mask applied"""
        nn_ut = ToyModel4()
        # print(summary(nn_ut, torch.rand((1, 3, 15)), show_input=True, show_hierarchical=True))
        x = torch.rand((32,) + tuple(nn_ut.input_shape[1:]))
        pit_net = PIT(nn_ut, input_example=x[0:1])
        nn_ut.eval()
        pit_net.eval()
        y = nn_ut(x)
        pit_y = pit_net(x)
        assert torch.all(torch.eq(y, pit_y))
        # Check that the original channel mask is set with all 1
        assert torch.sum(pit_net._inner_model
                                .conv0.out_channel_masker.alpha).item() == 10  # type: ignore
        # Define a custom mask for conv1
        new_mask = torch.Tensor([1, 1, 0, 0, 1, 1, 0, 1, 1, 1])
        conv1_alpha = Parameter(new_mask)
        pit_net._inner_model.conv1.out_channel_masker.alpha = conv1_alpha  # type: ignore
        pit_y = pit_net(x)
        # Before an add operation the two channel mask must be equal, so the new_mask
        # assigned on conv1 must also be present on conv0
        conv0_alpha = pit_net._inner_model.conv0.out_channel_masker.alpha  # type: ignore
        conv1_alpha = pit_net._inner_model.conv1.out_channel_masker.alpha  # type: ignore
        assert torch.all(torch.eq(conv0_alpha, conv1_alpha))  # type: ignore
        conv2_input = pit_net._inner_model\
                             .conv2.input_features_calculator.features.item()  # type: ignore
        assert conv2_input == torch.sum(new_mask).item()

        nn_ut = ToyModel5()
        x = torch.rand((32,) + tuple(nn_ut.input_shape[1:]))
        pit_net = PIT(nn_ut, input_example=x[0:1])
        # Check before a cat operation between 2 convolutional layers
        new_mask_0 = torch.Tensor([1, 1, 0, 0, 1, 1, 0, 0, 1, 1])
        conv0_alpha = Parameter(new_mask_0)
        pit_net._inner_model.conv0.out_channel_masker.alpha = conv0_alpha  # type: ignore
        pit_y = pit_net(x)
        conv2_input = pit_net._inner_model\
                             .conv2.input_features_calculator.features.item()  # type: ignore
        assert conv2_input == torch.sum(new_mask_0).item() * 2


    def test_keep_alive_masks_simple(self):
        # TODO: should generate more layers with random RF and Cout
        net = SimpleNN()
        pit_net = PIT(net, input_example=torch.rand((1, 3, 40)))
        # conv1 has a filter size of 5 and 57 output channels
        # note: the type: ignore tells pylance to ignore type checks on the next line
        ka_alpha = pit_net._inner_model.conv1.out_channel_masker._keep_alive  # type: ignore
        exp_ka_alpha = torch.tensor([1.0] + [0.0] * 56, dtype=torch.float32)
        self.assertTrue(torch.equal(ka_alpha, exp_ka_alpha), "Wrong keep-alive mask for channels")  # type: ignore
        ka_beta = pit_net._inner_model.conv1.timestep_masker._keep_alive  # type: ignore
        exp_ka_beta = torch.tensor([1.0] + [0.0] * 4, dtype=torch.float32)
        self.assertTrue(torch.equal(ka_beta, exp_ka_beta),"Wrong keep-alive mask for rf")  # type: ignore
        ka_gamma = pit_net._inner_model.conv1.dilation_masker._keep_alive  # type: ignore
        exp_ka_gamma = torch.tensor([1.0] + [0.0] * 2, dtype=torch.float32)
        self.assertTrue(torch.equal(ka_gamma, exp_ka_gamma), "Wrong keep-alive mask for dilation")  # type: ignore

    def test_c_matrices_simple(self):
        # TODO: should generate more layers with random RF and Cout
        net = SimpleNN()
        pit_net = PIT(net, input_example=torch.rand((1, 3, 40)))
        # conv1 has a filter size of 5 and 57 output channels
        c_beta = pit_net._inner_model.conv1.timestep_masker._c_beta  # type: ignore
        exp_c_beta = torch.tensor([
            [1, 1, 1, 1, 1],
            [0, 1, 1, 1, 1],
            [0, 0, 1, 1, 1],
            [0, 0, 0, 1, 1],
            [0, 0, 0, 0, 1],
        ], dtype=torch.float32)
        self.assertTrue(torch.equal(c_beta, exp_c_beta), "Wrong C beta matrix")  # type: ignore
        c_gamma = pit_net._inner_model.conv1.dilation_masker._c_gamma  # type: ignore
        exp_c_gamma = torch.tensor([
            [1, 1, 1],
            [0, 0, 1],
            [0, 1, 1],
            [0, 0, 1],
            [1, 1, 1],
        ], dtype=torch.float32)
        self.assertTrue(torch.equal(c_gamma, exp_c_gamma), "Wrong C gamma matrix")  # type: ignore

    def test_initial_inference(self):
        """ check that a PITModel just created returns the same output as its inner model"""
        net = SimpleNN()
        x = torch.rand((32,) + tuple(net.input_shape[1:]))
        pit_net = PIT(net, input_example=x[0:1])
        net.eval()
        pit_net.eval()
        y = net(x)
        pit_y = pit_net(x)
        assert torch.all(torch.eq(y, pit_y))
        # TODO: after an initial inference, we can check also if the out_channels_eff and k_eff
        # fields are set correctly for all layers, and other stuff

    @staticmethod
    def _execute_prepare(
            nn_ut: nn.Module,
            input_example: torch.Tensor,
            regularizer: str = 'size',
            exclude_names: Iterable[str] = (),
            exclude_types: Tuple[Type[nn.Module], ...] = (),
            autoconvert_layers=True):
        new_nn = PIT(nn_ut, input_example, regularizer, exclude_names=exclude_names,
                     exclude_types=exclude_types, autoconvert_layers=autoconvert_layers)
        return new_nn

    def _compare_prepared(self,
                          old_mod: nn.Module, new_mod: nn.Module,
                          old_top: nn.Module, new_top: DNAS,
                          exclude_names: Iterable[str] = (),
                          exclude_types: Tuple[Type[nn.Module], ...] = (),
                          autoconvert_layers=True):
        for name, child in old_mod.named_children():
            new_child = new_mod._modules[name]
            self._compare_prepared(child, new_child, old_top, new_top, exclude_names, exclude_types,
                                   autoconvert_layers)  # type: ignore
            if isinstance(child, nn.Conv1d):
                if (name not in exclude_names) and \
                        (not isinstance(child, exclude_types) and (autoconvert_layers)):
                    assert isinstance(new_child, PITConv1d)
                    assert child.out_channels == new_child.out_channels
                    # TODO: add more checks


if __name__ == '__main__':
    unittest.main(verbosity=2)
