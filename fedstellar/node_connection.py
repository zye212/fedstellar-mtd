# 
# This file an adaptation and extension of the p2pfl library (https://pypi.org/project/p2pfl/).
# Refer to the LICENSE file for licensing information.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#


import logging
import socket
import threading

from fedstellar.command import *
from fedstellar.communication_protocol import CommunicationProtocol
from fedstellar.config.config import Config
from fedstellar.utils.observer import Events, Observable


########################
#    NodeConnection    #
########################


class NodeConnection(threading.Thread, Observable):
    """
    This class represents a connection to a node. It is a thread, so it's going to process all messages in a background thread using the CommunicationProtocol.

    The NodeConnection can receive many messages in a single recv and exists 2 kinds of messages:
        - Binary messages (models)
        - Text messages (commands)

    Be careful, if the connection is broken, it will be closed. If the user wants to reconnect, he/she should create a new connection.

    Args:
        parent_node: The parent node of this connection.
        s: The socket of the connection.
        addr: The address of the node that is connected to.
    """

    ##############
    #    Init    #
    ##############

    def __init__(
            self, parent_node_name, s, addr, aes_cipher, tcp_buffer_size=(None, None), config: Config = None
    ):
        # Init supers
        threading.Thread.__init__(
            self,
            name=(
                    "node_connection-"
                    + parent_node_name
                    + "-"
                    + str(addr[0])
                    + ":"
                    + str(addr[1])
            ),
        )
        Observable.__init__(self)
        # Connection Loop
        self.__terminate_flag = threading.Event()
        self.__socket = s
        self.__socket_lock = threading.Lock()

        if tcp_buffer_size[0] is not None:
            self.__socket.setsockopt(
                socket.SOL_SOCKET, socket.SO_RCVBUF, tcp_buffer_size[0]
            )

        if tcp_buffer_size[1] is not None:
            self.__socket.setsockopt(
                socket.SOL_SOCKET, socket.SO_SNDBUF, tcp_buffer_size[1]
            )

        self.config = config

        # Atributes
        self.__addr = addr
        self.__param_bufffer = b""
        self.__model_ready = -1
        self.__aes_cipher = aes_cipher
        self.__model_initialized = False
        self.__models_aggregated = []
        # Communication Protocol
        self.comm_protocol = CommunicationProtocol(
            {
                CommunicationProtocol.BEAT: Beat_cmd(self),
                CommunicationProtocol.ROLE: Role_cmd(self),
                CommunicationProtocol.STOP: Stop_cmd(self),
                CommunicationProtocol.CONN_TO: Conn_to_cmd(self),
                CommunicationProtocol.START_LEARNING: Start_learning_cmd(self),
                CommunicationProtocol.STOP_LEARNING: Stop_learning_cmd(self),
                CommunicationProtocol.PARAMS: Params_cmd(self),
                CommunicationProtocol.MODELS_READY: Models_Ready_cmd(self),
                CommunicationProtocol.METRICS: Metrics_cmd(self),
                CommunicationProtocol.VOTE_TRAIN_SET: Vote_train_set_cmd(self),
                CommunicationProtocol.MODELS_AGGREGATED: Models_aggregated_cmd(self),
                CommunicationProtocol.MODEL_INITIALIZED: Model_initialized_cmd(self),
                CommunicationProtocol.TRANSFER_LEADERSHIP: Transfer_leadership_cmd(self),
            },
            self.config,
        )

    ##############
    #    Name    #
    ##############

    def get_addr(self):
        """
        Returns:
            (ip, port) The address of the node that is connected to.
        """
        return self.__addr

    def get_name(self):
        """
        Returns:
            The name of the node connected to.
        """
        return self.__addr[0] + ":" + str(self.__addr[1])

    ###################
    #    Main Loop    #
    ###################

    def start(self, force=False):
        """
        Start the connection. It will start the connection thread, this thread is receiving messages and processing them.

        Args:
            force: Determine if connection is going to keep alive even if it should not.
        """
        self.notify(Events.NODE_CONNECTED_EVENT, (self, force))
        return super().start()

    def run(self):
        """
        NodeConnection loop. Receive and process messages.
        """
        self.__socket.settimeout(self.config.participant["NODE_TIMEOUT"])
        amount_pending_params = 0
        param_buffer = b""
        while not self.__terminate_flag.is_set():
            try:
                # Receive message
                og_msg = b""
                if amount_pending_params == 0:
                    og_msg = self.__socket.recv(self.config.participant["BLOCK_SIZE"])

                else:
                    pending_fragment = self.__socket.recv(amount_pending_params)
                    og_msg = param_buffer + pending_fragment  # alinear el colapso
                    param_buffer = b""
                    amount_pending_params = 0

                # Decrypt message
                if self.__aes_cipher is not None:
                    # Guarantee block size (if TCP sctream is slow)
                    bytes_to_block_size = len(og_msg) % self.__aes_cipher.bs
                    # Decrypt
                    if bytes_to_block_size != 0:
                        msg = self.__aes_cipher.decrypt(
                            og_msg + self.__socket.recv(bytes_to_block_size)
                        )
                    else:
                        msg = self.__aes_cipher.decrypt(og_msg)
                else:
                    msg = og_msg

                # Process messages
                if msg != b"":
                    # Check if fragments are incomplete (collapse / TCP stream slow)
                    overflow = CommunicationProtocol.check_collapse(msg)
                    if overflow > 0:
                        param_buffer = og_msg[overflow:]
                        amount_pending_params = self.config.participant["BLOCK_SIZE"] - len(param_buffer)
                        msg = msg[:overflow]
                        logging.debug(
                            "[NODE_CONNECTION] Collapse detected: {}".format(
                                msg
                            )
                        )

                    else:
                        # Check if all bytes of param_buffer are received
                        amount_pending_params = (
                            CommunicationProtocol.check_params_incomplete(msg, self.config.participant["BLOCK_SIZE"])
                        )
                        if amount_pending_params != 0:
                            param_buffer = msg
                            continue

                    # Process message
                    # if len(str(msg)) > 300:
                    #     logging.info(
                    #        "[NODE_CONNECTION] Processing message: Too long [...]"
                    #    )
                    # else:
                    #    logging.info(
                    #        "[NODE_CONNECTION] Processing message: {}".format(msg)
                    #    )
                    exec_msgs, error = self.comm_protocol.process_message(msg)
                    if len(exec_msgs) > 0:
                        self.notify(
                            Events.PROCESSED_MESSAGES_EVENT, (self, exec_msgs)
                        )  # Notify the parent node

                    # Error happened
                    if error:
                        self.__terminate_flag.set()
                        logging.info(
                            "[NODE_CONNECTION] An error happened. Last error: {}".format(msg)
                        )

            except socket.timeout:
                logging.info(
                    "[NODE_CONNECTION] (NodeConnection Loop) Timeout"
                )
                self.__terminate_flag.set()
                break

            except Exception as e:
                logging.info(
                    "[NODE_CONNECTION] (NodeConnection Loop) Exception: {}".format(str(e))
                )
                self.__terminate_flag.set()
                break

        # Down Connection
        logging.info("[NODE_CONNECTION] Closed connection: {}".format(self.get_name()))
        self.notify(Events.END_CONNECTION_EVENT, self)
        self.__socket.close()

    def stop(self, local=False):
        """
        Stop the connection. Stops the main loop and closes the socket.

        Args:
            local: If true, the connection will be closed without notifying the other node.
        """
        if not local:
            self.send(CommunicationProtocol.build_stop_msg())
        self.__terminate_flag.set()

    ############################
    #    Processed Messages    #
    ############################

    def add_processed_messages(self, msgs):
        """
        Add to a list of communication protocol messages that have been processed. (By other nodes)
        Messages are added to avoid multiple processing of the same messages, also the non-processing
        of these messages avoid cycles in the network.

        Args:
            msgs: The list of messages that have been processed.

        """
        self.comm_protocol.add_processed_messages(msgs)

    ############################
    #    Model Ready Rounds    #
    ############################

    def set_model_ready_status(self, round):
        """
        Set the last ready round of the other node.

        Args:
            round: The last ready round of the other node.
        """
        self.__model_ready = round

    def get_model_ready_status(self):
        """
        Returns:
            The last ready round of the other node.
        """
        return self.__model_ready

    ###########################
    #    Model Initialized    #
    ###########################

    def set_model_initialized(self, value):
        """
        Set the model initialized.

        Args:
            value: True if the model is initialized, false otherwise.
        """
        self.__model_initialized = value

    def get_model_initialized(self):
        """
        Returns:
            The model initialized.
        """
        return self.__model_initialized

    ##########################
    #    Models Aggregated    #
    ##########################

    def add_models_aggregated(self, models):
        """
        Add the models aggregated.

        Args:
            models: Models aggregated.
        """
        self.__models_aggregated = list(set(models + self.__models_aggregated))

    def clear_models_aggregated(self):
        """
        Clear models aggregated.
        """
        self.__models_aggregated = []

    def get_models_aggregated(self):
        """
        Returns:
            The models aggregated.
        """
        return self.__models_aggregated

    #######################
    #    Params Buffer    #
    #######################

    def add_param_segment(self, data):
        """
        Add a segment of parameters to the buffer.

        Args:
            data: The segment of parameters.
        """
        self.__param_bufffer = self.__param_bufffer + data

    def get_params(self):
        """
        Returns:
            The parameters buffer content.
        """
        return self.__param_bufffer

    def clear_buffer(self):
        """
        Clear the params buffer.
        """
        self.__param_bufffer = b""

    ##################
    #    Messages    #
    ##################

    def send(self, data):
        """
        Tries to send a message to the other node.

        Args:
            data: The message to send.

        Returns:
            True if the message was sent, False otherwise.

        """
        # Check if the connection is still alive
        if not self.__terminate_flag.is_set():
            try:
                # Encrypt message
                if self.__aes_cipher is not None:
                    data = self.__aes_cipher.add_padding(
                        data
                    )  # -> It cant broke the model because it fills all the block space
                    data = self.__aes_cipher.encrypt(data)
                # Send message
                self.__socket_lock.acquire()
                self.__socket.sendall(data)
                self.__socket_lock.release()
                return True

            except Exception as e:
                # If some error happened, the connection is closed
                self.__terminate_flag.set()
                return False
        else:
            return False

    ###########################
    #    Command Callbacks    #
    ###########################

    def notify_heartbeat(self, node):
        """
        Notify that a heartbeat was received.
        """
        self.notify(Events.BEAT_RECEIVED_EVENT, node)

    def notify_role(self, node, role):
        """
        Notify that a heartbeat was received.
        """
        self.notify(Events.ROLE_RECEIVED_EVENT, (node, role))

    def notify_conn_to(self, h, p):
        """
        Notify to the parent node that `CONN_TO` has been received.
        """
        self.notify(Events.CONN_TO_EVENT, (h, p))

    def notify_start_learning(self, r, e):
        """
        Notify to the parent node that `START_LEARNING_EVENT` has been received.
        """
        self.notify(Events.START_LEARNING_EVENT, (r, e))

    def notify_stop_learning(self, cmd):
        """
        Notify to the parent node that `START_LEARNING_EVENT` has been received.
        """
        self.notify(Events.STOP_LEARNING_EVENT, None)

    def notify_params(self, params):
        """
        Notify to the parent node that `PARAMS` has been received.
        """
        self.notify(Events.PARAMS_RECEIVED_EVENT, (params))

    def notify_metrics(self, node, round, loss, metric):
        """
        Notify to the parent node that `METRICS` has been received.
        """
        self.notify(Events.METRICS_RECEIVED_EVENT, (node, round, loss, metric))

    def notify_train_set_votes(self, node, votes):
        """
        Set the last ready round of the other node.

        Args:
            votes:
            node:
            round: The last ready round of the other node.
        """
        self.notify(Events.TRAIN_SET_VOTE_RECEIVED_EVENT, (node, votes))

    def set_transfer_leadership(self, value):
        """
        Set the role of the node when the transfer leadership is received.

        Args:
            value: The role of the node when the transfer leadership is received.
        """
        logging.info("[NODE_CONNECTION] Transfer leadership received")
        logging.info("[NODE_CONNECTION] Previous role: {}".format(self.config.participant['device_args']['role']))
        self.config.participant['device_args']['role'] = value
        logging.info("[NODE_CONNECTION] New role: {}".format(self.config.participant['device_args']['role']))
