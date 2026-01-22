# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

import os
import networkx as nx

import openoptics.utils as utils
from openoptics.TimeFlowTable import Path, TimeFlowEntry
from openoptics.backend.backend_ns3 import BackendNs3
# from openoptics.backend.backend_mininet import BackendMininet

from typing import List, Union

class BaseNetwork:
    """
    The base class of optical networks.

    This class provides the foundation for creating and managing optical networks
    in OpenOptics. It includes topology and routing configurations,
    network monitoring, and interaction with the underlying backend.

    The class handles both Traffic-Oblivious (TO) and Traffic-Aware (TA) architectures,
    allowing for pre-defined topology or runtime reconfiguration.
    """

    def __init__(
        self,
        name,
        nb_node,
        nb_link=1,
        nb_host_per_tor=1,
        backend="Mininet",
        time_slice_duration_ms=128,
        arch_mode="TO",  # TO for traffic-oblivious, TA for traffic-aware
        use_webserver=True,
    ):
        """
        Initialize the BaseNetwork.

        Args:
            name (str): Name of the network
            backend (str): Backend of OpenOptics. "Mininet", "Testbed", or "ns3"
            nb_node (int): Number of nodes in the network
            nb_link (int, optional): Number of links per node (defaults to 1)
            nb_host_per_tor (int, optional): Number of hosts per ToR (defaults to 1)
            time_slice_duration_ms (int, optional): Duration of each time slice in milliseconds (defaults to 128)
            arch_mode (str, optional): architecture mode: "TO" or "TA" (defaults to "TO")
            use_webserver (bool, optional): Whether to use web server for dashboard (defaults to True)
        """

        self.name = name

        self.backend = None
        if (backend == "ns3"):
            self.backend = BackendNs3(
                nb_node,
                nb_link,
                nb_host_per_tor,
                time_slice_duration_ms,
                arch_mode
            )
        elif (backend == "Mininet"):
            self.backend = BackendMininet()
        else:
            raise ValueError(f"Unsupported backend {backend}")

        self.nb_time_slices = 1
        self.time_slice_duration_ms = time_slice_duration_ms
        self.arch_mode = arch_mode
        self.calendar_queue_mode = 0 if arch_mode == "TO" else 1

        self.slice_to_topo = {}
        self.mininet_net = None
        self.nb_node = nb_node
        self.nb_link = nb_link
        self.nb_host_per_tor = nb_host_per_tor  # Number of hosts for each ToR
        self.ip_to_tor = {}
        self.nodes_created = False

        self.use_webserver = use_webserver

        print("Setting up OpenOptics...")

    def __str__(self) -> str:
        """
        Return string representation of the network.

        Returns:
            str: Name of the network
        """
        return self.name

    def create_nodes(self):
        """Create nodes on the choice of backend"""
        self.backend.create_nodes()

    def cal_node_port_to_ocs_port(self, node_id, port_id):
        """
        Find the OCS's port that connects to a node's port.

        Args:
            node_id (int): ID of the ToR
            port_id (int): ID of the ToR's port

        Returns:
            int: the OCS's port
        """

        return self.backend.cal_node_port_to_ocs_port(node_id, port_id)

    def setup_ocs(self):
        """
        Generate commands for OCS forwarding.

        Creates and loads the OCS forwarding table entries based on
        the current topology configuration.
        """
        ocs_slice_port1_port2 = []
        for ts, graph in self.slice_to_topo.items():
            # print(f"edge list: {nx.to_edgelist(graph)}")
            # We used DiGraph to guarantee node1 and node2 are in added order.
            for node1, node2, attr in nx.to_edgelist(graph):
                port1, port2 = attr["port1"], attr["port2"]
                ocs_port1 = self.cal_node_port_to_ocs_port(node1, port1)
                ocs_port2 = self.cal_node_port_to_ocs_port(node2, port2)
                ocs_slice_port1_port2.append((ts, ocs_port1, ocs_port2))

        self.backend.setup_ocs(ocs_slice_port1_port2, self.nb_time_slices, self.time_slice_duration_ms)

    def start(self):
        """
        Start OpenOptics user interface (CLI, dashboard, ...).

        Traffic Oblivious. Initializes DeviceManager, starts CLI, and handles
        network shutdown.
        """
        self.backend.start()


    def start_traffic_aware(
        self, topo_func=None, routing_func=None, routing_mode=None, update_interval=1
    ) -> bool:
        """Deploy traffic aware architecture.

        Args:
            topo_func: traffic aware topology function with traffic matrix as input
            routing_func: routing function used by traffic aware architecture
            routing_mode: Source or Per-hop
            update_interval: interval in seconds to update topology and routing

        Return:
            Whether the traffic aware architecture is successfully deployed.
        """

        # In commercial switches, buffer is port-associated. Once the packet is buffered to a port,
        # it will be sent out from the same port. To use multi-port, we need to make additional
        # mapping between ports and nodes.
        # To keep the design simple, we limit the number of ports to 1 in TA for now.
        if self.nb_link != 1:
            raise ValueError("Traffic aware architecture only supports one link.")

        import threading

        stop_event = threading.Event()

        self.start_monitor()

        # initialize active calendar queue.
        self.activate_calendar_queue()

        def evolve():
            prev_circuits = []
            while not stop_event.is_set():
                metric = self.device_manager.get_device_metric()
                traffic_matrix = utils.metric_to_matrix(metric)
                if topo_func:
                    circuits = topo_func(
                        nb_node=self.nb_node,
                        nb_link=self.nb_link,
                        traffic_matrix=traffic_matrix,
                        prev_circuits=prev_circuits,
                    )

                    # Only re-deploy topology if there is a change
                    if prev_circuits != circuits:
                        prev_circuits = circuits
                        self.pause_calendar_queue()

                        assert self.deploy_topo(circuits, start_fresh=True)
                        # Now we have a static dst to queue mapping, so don't need to re-deploy routing.
                        # paths = routing_func(self.slice_to_topo)
                        # self.deploy_routing(paths, routing_mode, arch_mode="TA", start_fresh=True)
                        self.activate_calendar_queue()

                stop_event.wait(timeout=update_interval)

        evolve_thread = threading.Thread(target=evolve)
        evolve_thread.start()

        self.start_cli()
        stop_event.set()
        evolve_thread.join()
        self.stop_network()

    ##########################
    #    Optical Topology    #
    ##########################

    def connect(
        self, time_slice, node1, node2, port1=0, port2=0, unidirectional=False
    ) -> bool:
        """
        Connect two node ports at the given time slice by configuring OCS,
        if no optical connections haven't been built for both ports.

        Args:
            time_slice (int): The time slice to connect
            node1 (int): The first of two nodes to connect
            node2 (int): The second of two nodes to connect
            port1 (int, optional): The port the first node uses to connect. Defaults to 0.
            port2 (int, optional): The port the second node uses to connect. Defaults to 0.
            unidirectional (bool, optional): Whether connection is unidirectional. Defaults to False.

        Returns:
            bool: Whether the connect() was successful.
        """
        if not isinstance(time_slice, int) or time_slice < 0:
            raise ValueError(f"Invalid time slice {time_slice}.")
        if not isinstance(node1, int) or node1 < 0 or node1 >= self.nb_node:
            raise ValueError(
                f"Invalid node {node1}. Only nodes 0 to {self.nb_node - 1} are valid. Are you setting the correct nb_node when generating topology?"
            )
        if not isinstance(node2, int) or node2 < 0 or node2 >= self.nb_node:
            raise ValueError(
                f"Invalid node {node2}. Only nodes 0 to {self.nb_node - 1} are valid. Are you setting the correct nb_node when generating topology?"
            )

        if time_slice not in self.slice_to_topo.keys():
            # To-do: Change to multigraph to support multiple edges between two nodes

            # Fill missing time slices
            for added_time_slice in range(time_slice + 1):
                if added_time_slice not in self.slice_to_topo.keys():
                    # Even though ocs connect() provides bi-directional link,
                    # we use networkx.DiGraph to guarantee the correct node-port mapping,
                    # otherwise edge_list returns u,v in uncontrolled order.
                    self.slice_to_topo[added_time_slice] = nx.DiGraph()
                    self.slice_to_topo[added_time_slice].add_nodes_from(
                        range(self.nb_node)
                    )

        nodes = self.slice_to_topo[time_slice].nodes
        # Now we assume links are all bidirectional or all unidirectional.
        # So we only check for one direction.
        if ((port1 not in nodes[node1]) or (nodes[node1][port1] == False)) and (
            (port2 not in nodes[node2]) or (nodes[node2][port2] == False)
        ):
            # Ports are not occupied
            nodes[node1][port1] = True  # Keep track of port's occupancy
            nodes[node2][port2] = True
            # print(f"Time slice {time_slice} Connect node {node1} port {port1} to node {node2} port {port2} ")

            self.slice_to_topo[time_slice].add_edge(node1, node2, port1=port1, port2=port2)
            if unidirectional == False:
                self.slice_to_topo[time_slice].add_edge(
                    node2, node1, port1=port2, port2=port1
                )
            return True

        else:
            print(
                f"Port(s) occupied: Time slice {time_slice} can NOT connect node {node1} port {port1} to node {node2} port {port2} "
            )
            return False

    def disconnect(
        self, time_slice, node1, node2, port1=0, port2=0, unidirectional=False
    ) -> bool:
        """
        Disconnect two node ports at the given time slice.

        Args:
            node1 (int): First node
            port1 (int): Port of first node
            node2 (int): Second node
            port2 (int): Port of second node
            time_slice (int): Time slice to disconnect
            unidirectional (bool, optional): Whether disconnection is unidirectional. Defaults to False.

        Returns:
            bool: Whether the disconnection was successful
        """
        nodes = self.slice_to_topo[time_slice].nodes


        if time_slice not in self.slice_to_topo.keys():
            print(f"Time slice {time_slice} not found.")
            return False
        
        if self.slice_to_topo[time_slice].has_edge(node1, node2) == False:
            print(
                f"Time slice {time_slice} does not have edge between node {node1} and node {node2}."
            )
            return False

        if nodes[node1][port1] == False:
            print(
                f"Node {node1} Port {port1} is not the correct port connected to node {node2}."
            )
            return False
        
        if nodes[node2][port2] == False:
            print(
                f"Node {node2} Port {port2} is not the correct port connected to node {node1}."
            )
            return False
        
        nodes[node1][port1] = False
        nodes[node2][port2] = False

        self.slice_to_topo[time_slice].remove_edge(
            node1, node2
        )

        if unidirectional == False:
            self.slice_to_topo[time_slice].remove_edge(
                node2, node1
            )

        return True

    def deploy_topo(self, circuits=[], start_fresh=False) -> bool:
        """
        Create ocs schedules based on given circuits or existing slice_to_topo variable (updated by connect() before),
        and load them to OCS.
        Create nodes in the backend if it is the first time deploy_topo is called.

        Args:
            circuits (list, optional): A list of tuples (time_slice, node1, node2, port1, port2). Defaults to [].
            start_fresh (bool, optional): Whether to start with a fresh topology. Defaults to False.

        Returns:
            bool: Whether the given circuits are successfully deployed.
        """

        if start_fresh:
            self.slice_to_topo = {}

        for time_slice, node1, node2, port1, port2 in circuits:
            if not self.connect(time_slice, node1, node2, port1, port2):
                print("Topology deployment failed.")
                return False

        self.nb_time_slices = len(self.slice_to_topo.keys())
        self.backend.nb_time_slices = self.nb_time_slices
        if self.nb_time_slices == 0:
            raise Exception("No time slices deployed.")

        if self.nodes_created and self.use_webserver:
            self.dashboard.update_topo(self.slice_to_topo)

        if not self.nodes_created:
            self.create_nodes()
            self.nodes_created = True

        print("Deploying optical topologies...")
            
        # utils.clear_table(
        #     backend=self.backend,
        #     switch=self.mininet_net.nameToNode["ocs"],
        #     table_name="MyIngress.ocs_schedule",
        # )
        self.setup_ocs()

        return True

    def get_topo(self, time_slice=None) -> nx.Graph:
        """
        Get the topology (nx.Graph) at the given time slice.

        Args:
            time_slice (int): Time slice to retrieve topology for

        Returns:
            nx.Graph: The network topology at the given time slice, or None if not found
        """

        if time_slice is None:
            return self.slice_to_topo
        
        if time_slice not in self.slice_to_topo.keys():
            print("Time slice not found.")
            return None

        return self.slice_to_topo[time_slice]

    def pause_calendar_queue(self):
        """Pause traffic before reconfigure topology. Used in TA architecture.

        Sets the active queue for each node to itself, as no pkts should be there,
        this effectively pauses the calendar queues during topology reconfiguration.
        """
        for node1, node2, attr in nx.to_edgelist(self.slice_to_topo[0]):
            port1, port2 = attr["port1"], attr["port2"]
            assert port1 == 0 and port2 == 0, (
                "Now control calendar queue only supports one link per node"
            )

            # Set active queue to node_id, which is never used in TA
            # print(f"Pause calendar queue for node {node1}")
            self.device_manager.set_active_queue(
                f"tor{node1}", node1
            )  # only node1 because topo is DiGraph

    def activate_calendar_queue(self):
        """Update active calendar queues based on the current topology, for traffic-aware.

        Each calendar queue buffers packets to a destination node.
        Pause calendar queues whose packets' dst is not directly connected.
        """

        assert len(self.slice_to_topo.keys()) == 1, (
            f"Control calendar queue is only supported for TA with one time slice. \
            {len(self.slice_to_topo.keys())} time slices found."
        )

        for node1, node2, attr in nx.to_edgelist(self.slice_to_topo[0]):
            port1, port2 = attr["port1"], attr["port2"]
            assert port1 == 0 and port2 == 0, (
                "Now control calendar queue only supports one link per node"
            )
            self.device_manager.set_active_queue(f"tor{node1}", node2)
            # self.device_manager.set_active_queue(f"tor{node2}", node1)  # only node1 because topo is DiGraph

    ##########################
    #        Routing         #
    ##########################

    def add_time_flow_entry(
        self, 
        node_id, 
        entries: Union[List[TimeFlowEntry],TimeFlowEntry], 
        routing_mode="Per-hop"
    ) -> bool:
        """
        Add the time flow entry(s) to the node.

        Args:
            node_id (int): The node to add entries to
            entries (TimeFlowEntry or List[TimeFlowEntry]): A TimeFlowEntry or a list of TimeFlowEntry
            routing_mode (str): Source or Per-hop

        Returns:
            bool: Whether the entries were successfully added.
        """
        if isinstance(entries, TimeFlowEntry):
            entries = [entries]
        elif not isinstance(entries, list):
            raise ValueError("entries must be a TimeFlowEntry or a list of TimeFlowEntry")
        
        commands = ""
        if routing_mode == "Source":
            for entry in entries:
                commands += utils.tor_table_routing_source(entry, nb_time_slices=self.nb_time_slices)
        elif routing_mode == "Per-hop":
            for entry in entries:
                commands += utils.tor_table_routing_per_hop(entry, nb_time_slices=self.nb_time_slices)
        else:
            assert False, "Unsupported routing mode"

        if f"tor{node_id}" not in self.mininet_net.nameToNode.keys():
            print(f"Error: Try deploying paths to non-existent node: node{node_id}.")
            return False

        node = self.mininet_net.nameToNode[f"tor{node_id}"]
        #print(f"Load to ToR{node_id}:\n {commands}")
        return utils.load_table(self.backend, node, commands)

    def deploy_routing(
        self,
        paths: List[Path],
        routing_mode="Per-hop",
        arch_mode="TO",
        start_fresh=False,
    ) -> bool:
        """
        Deploy routing to nodes.

        Args:
            paths (List[Path]): A list of paths to be deployed to the network nodes
            routing_mode (str): The routing mode, either "Per-hop" or "Source"
            arch_mode (str, optional): The architecture mode, either "TO" (Traffic-Oblivious) or "TA" (Traffic-Aware). Defaults to "TO".
            start_fresh (bool, optional): If True, clears existing routing table entries before deploying new ones. Defaults to False.

        Returns:
            bool: True if routing deployment is successful
        """

        if start_fresh:
            print("Loading routings...")
            for node_id in range(self.nb_node):
                switch = self.mininet_net.nameToNode[f"tor{node_id}"]
                table_name = (
                    "per_hop_routing" if routing_mode == "Per-hop" else "source_routing"
                )
                utils.clear_table(
                    backend=self.backend, switch=switch, table_name=table_name
                )

        entry_dict = utils.path2entries(paths, routing_mode, arch_mode=arch_mode)

        # if len(entry_dict.keys() != self.nb_node):
        #    print("Warning: Paths are not complete.")

        for src, entries in entry_dict.items():
            self.backend.add_time_flow_entry(src, entries, routing_mode=routing_mode)
        return True
