import os

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import Link
from .p4_mininet import P4Switch, P4Host

from openoptics.DeviceManager import DeviceManager
from openoptics.Dashboard import Dashboard
from openoptics.TimeFlowTable import TimeFlowEntry
from openoptics.OpticalCLI import OpticalCLI
import openoptics.utils as utils
from openoptics.backend.backend_base import Backend



class BackendMininet(Backend):

    def __init__(self):

        self.thrift_port = 9090  # default thrift port
        self.host_tor_port = 0
        self.tor_host_port = 10  # One host per ToR for now
        assert nb_link > 0
        self.tor_ocs_ports = list(range(nb_link))

        self.mininet_topo = None

        """
        ocs_sw_path=f"openopticslib/optical_switch/optical_switch"
        ocs_json_path=f"openopticslib/ocs.json"
        tor_sw_path=f"openopticslib/tor_switch/tor_switch"
        tor_json_path=f"openopticslib/tor.json"
        cli_path=f"openopticslib/runtime_CLI"
        """
        root = ""
        ocs_sw_path = f"{root}/behavioral-model/targets/optical_switch/optical_switch"
        ocs_json_path = f"{root}/openoptics/p4/ocs/ocs.json"
        tor_sw_path = f"{root}/behavioral-model/targets/tor_switch/tor_switch"
        tor_json_path = f"{root}/openoptics/p4/tor/tor.json"
        cli_path = f"{root}/behavioral-model/targets/simple_switch/runtime_CLI"

        self.ocs_sw_path = ocs_sw_path
        self.ocs_json_path = ocs_json_path
        self.tor_sw_path = tor_sw_path
        self.tor_json_path = tor_json_path
        self.cli_path = cli_path

    def create_nodes(self):
        """
        Add OCS and Nodes to Mininet Topo().

        Creates the Mininet topology with OCS switch and ToR switches,
        establishes connections between them, and starts the network.
        To-do: Move backend-related code to a seperate class/file
        """
        os.system("mn -c > /dev/null 2>&1")

        print("Setting up Mininet network...")
        self.mininet_topo = Topo()
        # Add switches to mininet topology, store metadata in self.nodes dictionary
        ocs = self.mininet_topo.addSwitch(
            "ocs",
            dpid="0",
            sw_path=self.ocs_sw_path,
            json_path=self.ocs_json_path,
            thrift_port=self.thrift_port,
            pcap_dump=False,
            nb_time_slices=self.nb_time_slices,
            time_slice_duration_ms=self.time_slice_duration_ms,
            cls=P4Switch,
        )
        self.thrift_port += 1
        print("Optical switch created.")

        for tor_id in range(self.nb_node):
            tor_switch = self.mininet_topo.addSwitch(
                f"tor{tor_id}",
                dpid=f"{tor_id + 1}",
                sw_path=self.tor_sw_path,
                json_path=self.tor_json_path,
                thrift_port=self.thrift_port,
                pcap_dump=False,
                tor_id=tor_id,
                # In TA, we have a calendar queue for each node
                nb_time_slices=self.nb_time_slices
                if self.calendar_queue_mode == 0
                else self.nb_node,
                time_slice_duration_ms=self.time_slice_duration_ms,
                calendar_queue_mode=self.calendar_queue_mode,
                cls=P4Switch,
            )
            # OCS connect port 1 to tor1, port2 to tor2...
            # ToR connect port 0 to the OCS
            #? Why are we adding multiple links between the tor and ocs ?
            # - we have multiple links from the tor to the ocs
            # - appropriate links are specified in the routin table
            for link_id in range(self.nb_link):
                self.mininet_topo.addLink(
                    node1=ocs,
                    node2=tor_switch,
                    port1=self.cal_node_port_to_ocs_port(tor_id, link_id),
                    port2=self.tor_ocs_ports[link_id],
                )
            self.thrift_port += 1

            # Connect hosts to ToR switches
            for _ in range(self.nb_host_per_tor):  # Default to 1
                ip = f"10.0.{tor_id}.1"  # To-do: make it configurable in setting
                mac = "00:aa:bb:00:00:%02x" % tor_id
                host = self.mininet_topo.addHost("h" + str(tor_id), ip=ip, mac=mac)
                # print(f"h{tor_id}: {ip} {mac}")
                self.mininet_topo.addLink(
                    node1=host,
                    node2=tor_switch,
                    port1=self.host_tor_port,
                    port2=self.tor_host_port,
                    # cls=TCLink,
                    cls=Link,
                    bw=1000,
                    loss=0,
                )
                self.ip_to_tor[ip] = tor_id

        print(f"{self.nb_node} ToR switches created.")
        # for link in self.mininet_topo.links(withKeys=True, withInfo=True):
        #    print(link)
        print("Starting Mininet network...")
        self.mininet_net = Mininet(
            self.mininet_topo, host=P4Host, switch=P4Switch, controller=None
        )
        self.mininet_net.staticArp()

        for id in range(self.nb_node):
            h = self.mininet_net.get(f"h{id}")
            ip = f"10.0.{id}.1"
            mac = "00:aa:bb:00:00:%02x" % id
            h.setARP(ip, mac)

        self.mininet_net.start()

        self.setup_nodes()

    def setup_nodes(self):
        """
        Load utility tables into nodes.

        Configures the ToR switches with necessary routing and forwarding tables
        including IP to destination mappings, arrival verification, and port calculation.
        """

        print("Setting up switch tables...")

        ip_to_dst_commands = utils.tor_table_ip_to_dst(self.ip_to_tor)

        for tor_id in range(self.nb_node):
            arrive_at_dst = utils.tor_table_arrive_at_dst(tor_id, self.tor_host_port)
            verify_desired_node = utils.tor_table_verify_desired_node(tor_id)
            cal_port_enqueue = utils.tor_table_cal_port_slice_to_node(
                tor_id, self.slice_to_topo
            )

            switch = self.mininet_net.nameToNode[f"tor{tor_id}"]
            utils.load_table(
                backend=self.backend,
                switch=switch,
                table_commands=ip_to_dst_commands
                + arrive_at_dst
                + verify_desired_node
                + cal_port_enqueue,
                print_flag=False,
                save_flag=False,
            )

    def cal_node_port_to_ocs_port(self, node_id, port_id):
        return port_id * self.nb_node + node_id

    def setup_ocs(self, ocs_slice_port1_port2):
        ocs_commands = utils.gen_ocs_commands(ocs_slice_port1_port2)

        utils.load_table(
            backend=self.backend,
            switch=self.mininet_net.nameToNode["ocs"],  # to-be-updated
            table_commands=ocs_commands,
            print_flag=False,
        )

    def start_monitor(self):
        """
        Start OpenOptics DeviceManager and Dashboard.

        Initializes the monitoring system and starts the web dashboard
        if use_webserver is enabled. The dashboard is accessible at
        http://localhost:8001.
        """
        self.device_manager = DeviceManager(
            self.mininet_net,
            self.tor_ocs_ports,
            nb_queue=self.nb_time_slices if self.arch_mode == "TO" else self.nb_node,
        )

        if self.use_webserver:
            self.dashboard = Dashboard(
                self.slice_to_topo,
                self.device_manager,
                self.nb_link,
                nb_queue=self.nb_time_slices
                if self.calendar_queue_mode == 0
                else self.nb_node,
            )
            self.dashboard.start()
            os.system(
                "python3 /openoptics/openoptics/dashboard/manage.py runserver localhost:8001 > /dev/null 2>&1 &"
            )
            print("Access dashboard at http://localhost:8001")

    def start_cli(self):
        """
        Start OpenOptics CLI.

        Launches the command-line interface for interacting with the network.
        """
        OpticalCLI(self)

    def stop_network(self):
        """
        Stop the network.

        Stops the dashboard (if running) and the Mininet network.
        """
        if self.use_webserver:
            self.dashboard.stop()
        self.mininet_net.stop()

    def start(self):
        self.start_monitor()
        self.start_cli()
        self.stop_network()


    def add_time_flow_entry(
        self, 
        node_id, 
        entries, # Union[List[TimeFlowEntry],TimeFlowEntry], 
        routing_mode="Per-hop"
    ):
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