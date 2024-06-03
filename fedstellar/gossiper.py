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
import threading
import time

from fedstellar.config.config import Config
from fedstellar.utils.observer import Events, Observable


##################
#    Gossiper    #
##################


class Gossiper(threading.Thread, Observable):
    """
    Thread based gossiper. It gossips messages from list of pending messages. ``GOSSIP_MESSAGES_PER_ROUND`` are sended per iteration (``GOSSIP_FREC`` times per second).

    Communicates with node via observer pattern.

    Args:
        nodo_padre (str): Name of the parent node.
        neighbors (list): List of neighbors.

    """

    def __init__(self, node_name, neighbors, config: Config):
        Observable.__init__(self)
        threading.Thread.__init__(self, name=("gossiper-" + node_name))
        self.node_name = node_name
        self.__neighbors = neighbors  # list as reference of the original neighbors list
        self.config = config
        self.__msgs = {}
        self.__add_lock = threading.Lock()
        self.__terminate_flag = threading.Event()

    def add_messages(self, msgs, node):
        """
        Add messages to the list of pending messages.

        Args:
            msgs (list): List of messages to add.
            node (Node): Node that sent the messages.
        """
        self.__add_lock.acquire()
        for msg in msgs:
            self.__msgs[msg] = [node]
        self.__add_lock.release()

    def run(self):
        """
        Gossiper Main Loop. Sends `GOSSIP_MODEL_SENDS_BY_ROUND` messages ``GOSSIP_FREC`` times per second.
        """
        while not self.__terminate_flag.is_set():

            messages_left = self.config.participant["GOSSIP_MESSAGES_PER_ROUND"]

            # Lock
            self.__add_lock.acquire()
            begin = time.time()

            # Send to all the nodes except the ones that the message was already sent to
            if len(self.__msgs) > 0:
                msg_list = list(self.__msgs.items()).copy()
                logging.debug("[GOSSIPER] Message list: {}".format(msg_list))
                nei = set(self.__neighbors.copy())  # copy to avoid concurrent problems

                for msg, nodes in msg_list:
                    nodes = set(nodes)
                    sended = len(nei - nodes)

                    if messages_left - sended >= 0:
                        logging.debug("[GOSSIPER] Send msg: {} --> to {}".format(msg, list(nodes)))
                        self.notify(Events.GOSSIP_BROADCAST_EVENT, (msg, list(nodes)))
                        del self.__msgs[msg]
                        messages_left = messages_left - sended
                        if messages_left == 0:
                            break
                    else:
                        # Lists to concatenate / Sets to difference
                        excluded = (list(nei - nodes))[: abs(messages_left - sended)]
                        logging.debug("[GOSSIPER] Send msg: {} --> to {} | Excluded: {}".format(msg, list(nodes) + excluded, excluded))
                        self.notify(
                            Events.GOSSIP_BROADCAST_EVENT, (msg, list(nodes) + excluded)
                        )
                        self.__msgs[msg] = list(nodes) + list(nei - set(excluded))
                        break

            # Unlock
            self.__add_lock.release()

            # Wait to guarantee the frequency of gossipping
            time_diff = time.time() - begin
            time_sleep = 1 / self.config.participant["GOSSIP_MESSAGES_FREC"] - time_diff
            if time_sleep > 0:
                time.sleep(time_sleep)

    def stop(self):
        """
        Stop the gossiper.
        """
        self.__terminate_flag.set()
