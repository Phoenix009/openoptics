import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox, OpticalTopo, OpticalRouting

try:
    from ns import ns

    # ns.LogComponentEnableAll(ns.LOG_LEVEL_INFO);

    ns.LogComponentEnable("UdpEchoClientApplication", ns.LOG_LEVEL_INFO);
    ns.LogComponentEnable("UdpEchoServerApplication", ns.LOG_LEVEL_INFO);

except ModuleNotFoundError:
    raise SystemExit(
        "Error: ns3 Python module not found;"
        " Python bindings may not be enabled"
        " or your PYTHONPATH might not be properly configured"
    )

def setup_echo_server_client(net):
    # Add internet stack to the terminals

    internet = ns.InternetStackHelper()
    internet.Install(net.backend.tors)

    # We've got the "hardware" in place.  Now we need to add IP addresses.
    #
    ipv4 = ns.Ipv4AddressHelper()
    ipv4.SetBase(ns.Ipv4Address("10.1.1.0"), ns.Ipv4Mask("255.255.255.0"))
    ipv4.Assign(net.backend.tor_ports)

    #
    # Create UDP echo server on node 0 and client on node 1
    port = 9  # Discard port (RFC 863)

    echoServer = ns.UdpEchoServerHelper(port)
    serverApps = echoServer.Install(net.backend.tors.Get(0))
    serverApps.Start(ns.Seconds(1))
    serverApps.Stop(ns.Seconds(20))

    echoClient = ns.UdpEchoClientHelper(ns.Ipv4Address("10.1.1.1").ConvertTo(), port)
    echoClient.SetAttribute("MaxPackets", ns.UintegerValue(20))
    echoClient.SetAttribute("Interval", ns.TimeValue(ns.Seconds(1)))
    echoClient.SetAttribute("PacketSize", ns.UintegerValue(1024))

    clientApps = echoClient.Install(ns.NodeContainer(net.backend.tors.Get(1)))
    clientApps.Start(ns.Seconds(2))
    clientApps.Stop(ns.Seconds(20))

if __name__ == "__main__":
    nb_node = 4

    net = Toolbox.BaseNetwork(
        name="my_network",
        backend="ns3",
        nb_node=nb_node,
        time_slice_duration_ms=1024,  # in ms
        use_webserver=True,
    )

    circuits = OpticalTopo.round_robin(nb_node=nb_node)
    # print(circuits)
    assert net.deploy_topo(circuits)

    setup_echo_server_client(net)

    # paths = OpticalRouting.routing_direct(net.get_topo())
    # net.deploy_routing(paths, routing_mode="Per-hop")

    net.start()


# implementing TOR function. refere internet helper
# forwarding based on time flow table
