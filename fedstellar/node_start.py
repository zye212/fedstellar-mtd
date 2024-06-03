import logging
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))  # Parent directory where is the fedml_api module

from fedstellar.learning.pytorch.mnist.mnist import MNISTDataModule
from fedstellar.learning.pytorch.femnist.femnist import FEMNISTDataModule
from fedstellar.learning.pytorch.syscall.syscall import SYSCALLDataModule
from fedstellar.learning.pytorch.cifar10.cifar10 import CIFAR10DataModule

from fedstellar.config.config import Config
from fedstellar.learning.pytorch.mnist.models.mlp import MNISTModelMLP
from fedstellar.learning.pytorch.mnist.models.cnn import MNISTModelCNN
from fedstellar.learning.pytorch.femnist.models.cnn import FEMNISTModelCNN
from fedstellar.learning.pytorch.syscall.models.mlp import SyscallModelMLP
from fedstellar.learning.pytorch.syscall.models.autoencoder import SyscallModelAutoencoder
from fedstellar.learning.pytorch.cifar10.models.resnet import CIFAR10ModelResNet
from fedstellar.learning.pytorch.cifar10.models.fastermobilenet import FasterMobileNet
from fedstellar.learning.pytorch.cifar10.models.simplemobilenet import SimpleMobileNetV1
from fedstellar.learning.pytorch.syscall.models.svm import SyscallModelSGDOneClassSVM
from fedstellar.node import Node

os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"


def main():
    config_path = str(sys.argv[1])
    config = Config(entity="participant", participant_config_file=config_path)

    n_nodes = config.participant["scenario_args"]["n_nodes"]
    experiment_name = config.participant["scenario_args"]["name"]
    model_name = config.participant["model_args"]["model"]
    idx = config.participant["device_args"]["idx"]
    hostdemo = config.participant["network_args"]["ipdemo"]
    host = config.participant["network_args"]["ip"]
    port = config.participant["network_args"]["port"]
    neighbors = config.participant["network_args"]["neighbors"].split()

    rounds = config.participant["scenario_args"]["rounds"]
    epochs = config.participant["training_args"]["epochs"]

    aggregation_algorithm = config.participant["aggregator_args"]["algorithm"]

    dataset = config.participant["data_args"]["dataset"]
    model = None
    if dataset == "MNIST":
        dataset = MNISTDataModule(sub_id=idx, number_sub=n_nodes, iid=True)
        if model_name == "MLP":
            model = MNISTModelMLP()
        elif model_name == "CNN":
            model = MNISTModelCNN()
        else:
            raise ValueError(f"Model {model} not supported")
    elif dataset == "FEMNIST":
        dataset = FEMNISTDataModule(sub_id=idx, number_sub=n_nodes, root_dir=f"{sys.path[0]}/data")
        if model_name == "CNN":
            model = FEMNISTModelCNN()
        else:
            raise ValueError(f"Model {model} not supported")
    elif dataset == "SYSCALL":
        dataset = SYSCALLDataModule(sub_id=idx, number_sub=n_nodes, root_dir=f"{sys.path[0]}/data")
        if model_name == "MLP":
            model = SyscallModelMLP()
        elif model_name == "SVM":
            model = SyscallModelSGDOneClassSVM()
        elif model_name == "Autoencoder":
            model = SyscallModelAutoencoder()
        else:
            raise ValueError(f"Model {model} not supported")
    elif dataset == "CIFAR10":
        dataset = CIFAR10DataModule(sub_id=idx, number_sub=n_nodes, root_dir=f"{sys.path[0]}/data")
        if model_name == "ResNet9":
            model = CIFAR10ModelResNet(classifier="resnet9")
        elif model_name == "ResNet18":
            model = CIFAR10ModelResNet(classifier="resnet18")
        elif model_name == "fastermobilenet":
            model = FasterMobileNet()
        elif model_name == "simplemobilenet":
            model = SimpleMobileNetV1()
        else:
            raise ValueError(f"Model {model} not supported")
    else:
        raise ValueError(f"Dataset {dataset} not supported")

    if aggregation_algorithm == "FedAvg":
        pass
    else:
        raise ValueError(f"Aggregation algorithm {aggregation_algorithm} not supported")

    node = Node(
        idx=idx,
        experiment_name=experiment_name,
        model=model,
        data=dataset,
        hostdemo=hostdemo,
        host=host,
        port=port,
        config=config,
        encrypt=False
    )

    node.start()
    print("Node started, grace time for network start-up (30s)")
    time.sleep(30)  # Wait for the participant to start and register in the network

    # Node Connection to the neighbors
    for i in neighbors:
        print(f"Connecting to {i}")
        node.connect_to(i.split(':')[0], int(i.split(':')[1]), full=False)
        time.sleep(5)

    logging.info(f"Neighbors: {node.get_neighbors()}")
    logging.info(f"Network nodes: {node.get_network_nodes()}")

    start_node = config.participant["device_args"]["start"]

    if start_node:
        node.set_start_learning(rounds=rounds, epochs=epochs)  # rounds=10, epochs=5


if __name__ == "__main__":
    os.system("clear")
    main()
