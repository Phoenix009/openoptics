from openoptics.backend.backend_base import Backend
from openoptics.TimeFlowTable import Path, TimeFlowEntry

try:
    from ns import ns

except ModuleNotFoundError:
    raise SystemExit(
        "Error: ns3 Python module not found;"
        " Python bindings may not be enabled"
        " or your PYTHONPATH might not be properly configured"
    )

class BackendNs3(Backend):

    def __init__(
            self,
            nb_node,
            nb_link=1,
            nb_host_per_tor=1,
            time_slice_duration_ms=128,
            arch_mode="TO",  # TO for traffic-oblivious, TA for traffic-aware
        ):
        self.nodeid_to_ocs_port = {}

        self.ocs = None

        self.tors = None
        self.tor_net_devices = ns.NetDeviceContainer()
        self.tor_ocs_ports = ns.NetDeviceContainer()
        self.ocs_tor_ports = ns.NetDeviceContainer()

        self.hosts = None
        self.host_tor_ports = ns.NetDeviceContainer()
        self.tor_host_ports = ns.NetDeviceContainer()

        self.nb_time_slices = None
        self.time_slice_duration_ms = time_slice_duration_ms

        self.arch_mode = arch_mode
        self.calendar_queue_mode = 0 if arch_mode == "TO" else 1

        self.nb_node = nb_node
        self.nb_link = nb_link
        self.nb_host_per_tor = nb_host_per_tor  # Number of hosts for each ToR
        self.nodes_created = False

    def create_nodes(self):
        """
        Add OCS and Nodes to ns3 topology.

        Creates the ns3 topology with OCS switch and ToR switches,
        establishes connections between them.
        To-do: Move backend-related code to a seperate class/file
        """

        self.hosts = ns.NodeContainer()
        self.hosts.Create(self.nb_node * self.nb_host_per_tor)

        self.tors = ns.NodeContainer()
        self.tors.Create(self.nb_node)

        ocs_switch = ns.NodeContainer()
        ocs_switch.Create(1)

        self.ocs = ocs_switch.Get(0)

        timeflow_port_helper = ns.TimeflowPortHelper()
        timeflow_port_helper.SetDeviceAttribute("DataRate", ns.DataRateValue(ns.DataRate(5000000)))
        timeflow_port_helper.SetChannelAttribute("Delay", ns.TimeValue(ns.MilliSeconds(2)))

        timeflow_bridge_helper = ns.TimeflowBridgeHelper()
        timeflow_bridge_helper.SetDeviceAttribute("TimeSliceCount", ns.UintegerValue(int(self.nb_time_slices)))
        timeflow_bridge_helper.SetDeviceAttribute("TimeSliceDuration", ns.TimeValue(ns.MilliSeconds(self.time_slice_duration_ms)))

        for tor_id in range(self.nb_node):
            tor_node = self.tors.Get(tor_id)

            host_ports = ns.NetDeviceContainer()
            tor_ports = ns.NetDeviceContainer()

            for host in range(self.nb_host_per_tor):
                host_id = (tor_id * self.nb_host_per_tor) + host
                host_tor_link = timeflow_port_helper.Install(ns.NodeContainer(
                        ns.NodeContainer(self.hosts.Get(host_id)),
                        ns.NodeContainer(tor_node),
                    ))
                host_port = host_tor_link.Get(0)
                host_ports.Add(host_port)

                tor_port = host_tor_link.Get(1)
                tor_ports.Add(tor_port)

            self.host_tor_ports.Add(host_ports)
            self.tor_host_ports.Add(tor_ports)

            tor_ocs_link = timeflow_port_helper.Install(ns.NodeContainer(ns.NodeContainer(tor_node), ocs_switch))
            tor_port = tor_ocs_link.Get(0)
            ocs_port = tor_ocs_link.Get(1)

            self.tor_ocs_ports.Add(tor_port)
            tor_ports.Add(tor_port)

            self.ocs_tor_ports.Add(ocs_port)
            self.nodeid_to_ocs_port[tor_id] = ocs_port

            bridge_net_devices = timeflow_bridge_helper.Install(tor_node, tor_ports)
            self.tor_net_devices.Add(bridge_net_devices)


    def cal_node_port_to_ocs_port(self, node_id, port_id):
        return self.nodeid_to_ocs_port.get(node_id)

    def setup_ocs(self, ocs_slice_port1_port2, nb_time_slices, time_slice_duration_ms):
        ocs_helper = ns.OCSHelper()
        ocs_helper.SetDeviceAttribute("TimeSliceCount", ns.UintegerValue(nb_time_slices))
        ocs_helper.SetDeviceAttribute("TimeSliceDuration", ns.TimeValue(ns.MilliSeconds(time_slice_duration_ms)))

        schedule = ns.OCSSchedule()


        for (ts, ocs_port1, ocs_port2) in ocs_slice_port1_port2:

            ocs_port1_mac = ns.Mac48Address.ConvertFrom(ocs_port1.GetAddress())
            ocs_port2_mac = ns.Mac48Address.ConvertFrom(ocs_port2.GetAddress())

            schedule.insert(((ts, ocs_port1_mac), ocs_port2))
            schedule.insert(((ts, ocs_port2_mac), ocs_port1))

        ocs_helper.Install(self.ocs, self.ocs_tor_ports, schedule)
    
    def start(self):
        ns.Simulator.Run()
        ns.Simulator.Destroy()

    def add_time_flow_entry_perhop(
        self,
        tor_id,
        entry,
        nb_time_slices=None
    ):
        if len(entry.hops) != 1:
            print(
                f"Warning: Find multi-hop time flow entry ({entry}) in Per-hop forwarding mode. Trim following hops."
            )

        tor_net_device = self.tor_net_devices.Get(tor_id)

        dst_port = self.host_tor_ports.Get(entry.dst)
        dst_mac = ns.Mac48Address.ConvertFrom(dst_port.GetAddress())

        # this will sometimes be a tor_ocs port and tor_host port
        # this will always be tor_ocs port
        hop = entry.hops[0]
        out_port = self.tor_ocs_ports.Get(tor_id)


        if entry.arrival_ts is None:
            # Flow table with wildcard arrival time slice
            for arrival_ts in range(nb_time_slices):
                tor_net_device.addRouteEntry(
                    arrival_ts,
                    dst_mac,
                    out_port,
                    hop.send_ts
                    )
        else:
            # Regular time flow table
            tor_net_device.addRouteEntry(
                entry.arrival_ts,
                dst_mac,
                out_port,
                hop.send_ts
                )


    def add_time_flow_entry(
        self, 
        tor_id, 
        entries, # Union[List[TimeFlowEntry],TimeFlowEntry], 
        routing_mode="Per-hop"
    ):
        if isinstance(entries, TimeFlowEntry):
            entries = [entries]
        elif not isinstance(entries, list):
            raise ValueError("entries must be a TimeFlowEntry or a list of TimeFlowEntry")
        
        if routing_mode == "Source":
            assert False, "Not implemented source routing in ns3 backend"
            # for entry in entries:
            #     commands += utils.tor_table_routing_source(entry, nb_time_slices=self.nb_time_slices)
        elif routing_mode == "Per-hop":
            for index, entry in enumerate(entries):
                self.add_time_flow_entry_perhop(tor_id, entry, self.nb_time_slices)
        else:
            assert False, "Unsupported routing mode"

        # if f"tor{tor_id}" not in self.mininet_net.nameToNode.keys():
        #     print(f"Error: Try deploying paths to non-existent node: node{node_id}.")
        #     return False

        # node = self.mininet_net.nameToNode[f"tor{node_id}"]
        # #print(f"Load to ToR{node_id}:\n {commands}")
        # return utils.load_table(self.backend, node, commands)