#! /usr/bin/env python3

import argparse
import helper
import json
import os
import platform
import printer
import requests
import subprocess
import shlex
import time


from typing import List, Optional, Union


PROGRAM = "eosio-launcher-service"

DEFAULT_ADDRESS = "127.0.0.1"
DEFAULT_PORT = 1234
DEFAULT_DIR = "../build"
DEFAULT_FILE = os.path.join(".", "programs", PROGRAM, PROGRAM)
DEFAULT_START = False
DEFAULT_KILL = False
DEFAULT_VERBOSITY = 1
DEFAULT_MONOCHROME = False

DEFAULT_CLUSTER_ID = 0
DEFAULT_TOPOLOGY = "mesh"
DEFAULT_TOTAL_NODES = 4
DEFAULT_TOTAL_PRODUCERS = 4
DEFAULT_PRODUCER_NODES = 4
DEFAULT_UNSTARTED_NODES = 0

HELP_HELP = "Show this message and exit"
HELP_ADDRESS = "Address of launcher service"
HELP_PORT = "Listening port of launcher service"
HELP_DIR = "Working directory"
HELP_FILE = "Path to local launcher service file"
HELP_START = "Always start a new launcher service"
HELP_KILL = "Kill existing launcher services (if any)"
HELP_VERBOSE = "Verbosity level (-v for 1, -vv for 2, ...)"
HELP_SILENT = "Set verbosity level at 0 (keep silent)"
HELP_MONOCHROME = "Print in black and white instead of colors"

HELP_CLUSTER_ID = "Cluster ID to launch with"
HELP_TOPOLOGY = "Cluster topology to launch with"
HELP_TOTAL_NODES = "Number of total nodes"
HELP_TOTAL_PRODUCERS = "Number of total producers"
HELP_PRODUCER_NODES = "Number of nodes that have producers"
HELP_UNSTARTED_NODES = "Number of unstarted nodes"




class CommandLineArguments:
    def __init__(self, *templates):
        args = self.parse(*templates)
        if "service" in templates:
            self.address = args.address
            self.port = args.port
            self.dir = args.dir
            self.file = args.file
            self.start = args.start
            self.kill = args.kill
            self.verbosity = args.verbosity
            self.monochrome = args.monochrome

        if "cluster" in templates:
            self.cluster_id = args.cluster_id
            self.topology = args.topology
            self.total_nodes = args.total_nodes
            self.total_producers = args.total_producers
            self.producer_nodes = args.producer_nodes
            self.unstarted_nodes = args.unstarted_nodes


    @staticmethod
    def parse(*templates):
        HEADER = printer.String().decorate("Launcher Service for EOS Testing Framework", style="underline", fcolor="green")
        OFFSET = 5

        parser = argparse.ArgumentParser(description=HEADER, add_help=False, formatter_class=lambda prog: argparse.RawTextHelpFormatter(prog, max_help_position=50))
        info = lambda text, value: "{} ({})".format(printer.pad(text, left=OFFSET, total=50, char=' ', sep=""), value)

        if "service" in templates:
            parser.add_argument("-a", "--address", type=str, metavar="IP", help=info(HELP_ADDRESS, DEFAULT_ADDRESS))
            parser.add_argument("-p", "--port", type=int, help=info(HELP_PORT, DEFAULT_PORT))
            parser.add_argument("-d", "--dir", type=str, help=info(HELP_DIR, DEFAULT_DIR))
            parser.add_argument("-f", "--file", type=str, help=info(HELP_FILE, DEFAULT_FILE))
            parser.add_argument("-s", "--start", action="store_true", default=None, help=info(HELP_START, DEFAULT_START))
            parser.add_argument("-k", "--kill", action="store_true", default=None, help=info(HELP_KILL, DEFAULT_KILL))

        if "cluster" in templates:
            parser.add_argument("-i", "--cluster-id", dest="cluster_id", type=int, metavar="ID", help=info(HELP_CLUSTER_ID, DEFAULT_CLUSTER_ID))
            parser.add_argument("-t", "--topology", type=str, metavar="SHAPE", help=info(HELP_TOPOLOGY, DEFAULT_TOPOLOGY))
            parser.add_argument("-n", "--total-nodes", dest="total_nodes", type=int, metavar="NUM", help=info(HELP_TOTAL_NODES, DEFAULT_TOTAL_NODES))
            parser.add_argument("-y", "--total-producers", dest="total_producers", type=int, metavar="NUM", help=info(HELP_TOTAL_PRODUCERS, DEFAULT_TOTAL_PRODUCERS))
            parser.add_argument("-z", "--producer-nodes", dest="producer_nodes", type=int, metavar="NUM", help=info(HELP_PRODUCER_NODES, DEFAULT_PRODUCER_NODES))
            parser.add_argument("-u", "--unstarted-nodes", dest="unstarted_nodes", type=int, metavar="NUM", help=info(HELP_UNSTARTED_NODES, DEFAULT_UNSTARTED_NODES))

        if "service" in templates:
            verbosity = parser.add_mutually_exclusive_group()
            verbosity.add_argument("-v", "--verbose", dest="verbosity", action="count", default=None, help=info(HELP_VERBOSE, DEFAULT_VERBOSITY))
            verbosity.add_argument("-x", "--silent", dest="verbosity", action="store_false", default=None, help=info(HELP_SILENT, not DEFAULT_VERBOSITY))
            parser.add_argument("-m", "--monochrome", action="store_true", default=None, help=info(HELP_MONOCHROME, DEFAULT_MONOCHROME))

        parser.add_argument("-h", "--help", action="help", help=' ' * OFFSET + HELP_HELP)

        return parser.parse_args()




class Service:
    def __init__(self, address=None, port=None, dir=None, file=None, start=None, kill=None, verbosity=None, monochrome=None, args=None, dont_connect=False):
        # configure service
        self.address    = helper.override(DEFAULT_ADDRESS,      address,    args.address    if args else None)
        self.port       = helper.override(DEFAULT_PORT,         port,       args.port       if args else None)
        self.dir        = helper.override(DEFAULT_DIR,          dir,        args.dir        if args else None)
        self.file       = helper.override(DEFAULT_FILE,         file,       args.file       if args else None)
        self.start      = helper.override(DEFAULT_START,        start,      args.start      if args else None)
        self.kill       = helper.override(DEFAULT_KILL,         kill,       args.kill       if args else None)
        self.verbosity  = helper.override(DEFAULT_VERBOSITY,    verbosity,  args.verbosity  if args else None)
        self.monochrome = helper.override(DEFAULT_MONOCHROME,   monochrome, args.monochrome if args else None)

        # determine remote or local launcher service to connect to
        if self.address in ("127.0.0.1", "localhost"):
            self.remote = False
        else:
            self.remote = True
            self.file = self.start = self.kill = None

        # register printer
        self.print = printer.Print(invisible=not self.verbosity, monochrome=self.monochrome)
        self.string = printer.String(invisible=not self.verbosity, monochrome=self.monochrome)
        self.alert = printer.String(monochrome=self.monochrome)
        if self.verbosity > 2:
            self.print.response = lambda resp: self.print.response_in_full(resp)
        elif self.verbosity == 2:
            self.print.response = lambda resp: self.print.response_with_prompt(resp)
        elif self.verbosity == 1:
            self.print.response = lambda resp: self.print.response_in_short(resp)
        else:
            self.print.response = lambda resp: None
        self.string.offset = 0 if self.monochrome else 9

        if not dont_connect:
            self.connect()


    def connect(self):
        # print system info
        self.print_system_info()

        # print configuration
        self.print_config()

        # change working directory
        self.print_header("change working directory")
        os.chdir(self.dir)
        self.print.vanilla("{:70}{}".format("Current working directory", os.getcwd()))

        # connect to remote service and return
        if self.remote:
            self.connect_to_remote_service()
            return

        # connect to launcher service
        self.print_header("connect to launcher service")
        spid = self.get_service_pid()
        if self.kill:
            self.kill_service(spid)
            spid.clear()
        if spid and not self.start:
            self.connect_to_local_service(spid[0])
        else:
            self.start_service()


    # NOTE: may cancel sleep
    def print_header(self, text, sleep=0):
        self.print.vanilla(printer.pad(self.string.decorate(text, fcolor="black", bcolor="cyan")))
        time.sleep(sleep)


    def print_system_info(self):
        self.print_header("system info")
        self.print.vanilla("{:70}{}".format("UTC Time", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())))
        self.print.vanilla("{:70}{}".format("Local Time", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
        self.print.vanilla("{:70}{}".format("Platform", platform.platform()))


    def print_config(self):
        self.print_header("service configuration")
        self.print_config_helper("-a: address",     HELP_ADDRESS,       self.address,       DEFAULT_ADDRESS)
        self.print_config_helper("-p: port",        HELP_PORT,          self.port,          DEFAULT_PORT)
        self.print_config_helper("-d: dir",         HELP_DIR,           self.dir,           DEFAULT_DIR)
        self.print_config_helper("-f: file",        HELP_FILE,          self.file,          DEFAULT_FILE)
        self.print_config_helper("-s: start",       HELP_START,         self.start,         DEFAULT_START)
        self.print_config_helper("-k: kill",        HELP_KILL,          self.kill,          DEFAULT_KILL)
        self.print_config_helper("-v: verbose",     HELP_VERBOSE,       self.verbosity,     DEFAULT_VERBOSITY)
        self.print_config_helper("-m: monochrome",  HELP_MONOCHROME,    self.monochrome,    DEFAULT_MONOCHROME)


    def print_config_helper(self, label, help, value, default_value, label_width=22, help_width=48):
        self.print.vanilla("{:{label_offset_width}}{:{help_width}}{}"
                            .format(self.string.yellow(label), help,
                                    self.string.blue(value) if value != default_value else self.string.vanilla(value),
                                    label_offset_width=label_width+self.string.offset,
                                    help_width=help_width))

    # TODO
    def connect_to_remote_service(self):
        pass


    def connect_to_local_service(self, pid):
        current_port = self.get_service_port(pid)
        current_file = self.get_service_file(pid)
        self.print.green("Connecting to existing launcher service with process ID [{}].".format(pid))
        self.print.green("No new launcher service will be started.")
        self.print.vanilla("Configuration of existing launcher service:")
        self.print.vanilla("--- Listening port: [{}]".format(self.string.yellow(current_port)))
        self.print.vanilla("--- Path to file: {}".format(self.string.vanilla(current_file)))
        if self.port != current_port:
            self.print.yellow("Warning: port setting (port = {}) ignored.".format(self.port))
            self.port = current_port
        if self.file != current_file:
            self.print.yellow("Warning: file setting (file = {}) ignored.".format(self.file))
            self.file = current_file
        self.print.vanilla("To always start a new launcher service, pass {} or {}.".format(self.string.yellow("-s"), self.string.yellow("--start")))
        self.print.vanilla("To kill existing launcher services, pass {} or {}.".format(self.string.yellow("-k"), self.string.yellow("--kill")))


    def start_service(self):
        self.print.green("Starting a new launcher service.")
        subprocess.Popen([self.file, "--http-server-address=0.0.0.0:{}".format(self.port), "--http-threads=4"])
        assert self.get_service_pid(), self.alert.red("Launcher service is not started properly.")


    def kill_service(self, spid=None):
        spid = self.get_service_pid() if spid is None else spid
        for x in spid:
            self.print.yellow("Killing exisiting launcher service with process ID [{}].".format(x))
            subprocess.run(["kill", "-SIGTERM", str(x)])


    def get_service_pid(self) -> List[int]:
        """Returns a list of 0, 1, or more process IDs"""
        spid = helper.pgrep(PROGRAM)
        if len(spid) == 0:
            self.print.yellow("No launcher is running currently.")
        elif len(spid) == 1:
            self.print.green("Launcher service is running with process ID [{}].".format(spid[0]))
        else:
            self.print.green("Multiple launcher services are running with process IDs {}".format(spid))
        return spid


    def get_service_port(self, pid):
        res = subprocess.Popen(["ps", "-p", str(pid), "-o", "command="], stdout=subprocess.PIPE).stdout.read().decode("ascii")
        shlex.split(res)
        for x in shlex.split(res):
            if x.startswith("--http-server-address"):
                return int(x.split(':')[-1])
        assert False, self.alert.red("Failed to get --http-server-address from process ID {}!".format(pid))


    def get_service_file(self, pid):
        return subprocess.Popen(["ps", "-p", str(pid), "-o", "comm="], stdout=subprocess.PIPE).stdout.read().rstrip().decode("ascii")




class Cluster:
    def __init__(self, service, cluster_id=None, topology=None, total_nodes=None, total_producers=None, producer_nodes=None, unstarted_nodes=None, args=None, dont_bootstrap=False):
        """
        Bootstrap
        ---------
        1. launch a cluster
        2. get cluster info
        3. create bios account
        4. schedule protocol feature activations
        5. set eosio.token contract
        6. create tokens
        7. issue tokens
        8. set system contract
        9. init system contract
        10. create producer accounts
        11. register producers
        12. vote for producers
        13. verify head producer
        """

        # register service
        self.service = service
        self.print = service.print
        self.string = service.string
        self.print_header = service.print_header
        self.print_config_helper = service.print_config_helper

        # configure cluster
        self.cluster_id         = helper.override(DEFAULT_CLUSTER_ID,           cluster_id,         args.cluster_id         if args else None)
        self.topology           = helper.override(DEFAULT_TOPOLOGY,             topology,           args.topology           if args else None)
        self.total_nodes        = helper.override(DEFAULT_TOTAL_NODES,          total_nodes,        args.total_nodes        if args else None)
        self.total_producers    = helper.override(DEFAULT_TOTAL_PRODUCERS,      total_producers,    args.total_producers    if args else None)
        self.producer_nodes     = helper.override(DEFAULT_PRODUCER_NODES,       producer_nodes,     args.producer_nodes     if args else None)
        self.unstarted_nodes    = helper.override(DEFAULT_UNSTARTED_NODES,      unstarted_nodes,    args.unstarted_nodes    if args else None)

        # reconcile conflict in config
        self.reconcile_config()

        # check for potential problems in config
        self.check_config()

        # establish connection between nodes and producers
        self.nodes = []
        self.producers = {}
        q, r = divmod(self.total_producers, self.producer_nodes)
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        for i in range(self.total_nodes):
            self.nodes += [{"node_id": i}]
            if i < self.producer_nodes:
                prod = [] if i else ["eosio"]
                for j in range(i * q + r if i else 0, (i + 1) * q + r):
                    name = "defproducer" + alphabet[j]
                    prod.append(name)
                    self.producers[name] = i
                self.nodes[i]["producers"] = prod

        if not dont_bootstrap:
            self.bootstrap()


    def reconcile_config(self):
        if self.producer_nodes > self.total_producers:
            self.print_header("resolve conflict in cluster configuration")
            self.print.vanilla("Conflict: total producers ({}) <= producer nodes ({}).".format(self.total_producers, self.producer_nodes))
            self.print.vanilla("Resolution: total_producers takes priority over producer_nodes.")
            self.print.yellow("Warning: producer nodes setting (producer_nodes = {}) ignored.".format(self.producer_nodes))
            self.producer_nodes = self.total_producers


    def check_config(self):
        assert self.cluster_id >= 0
        assert self.total_nodes >= self.producer_nodes + self.unstarted_nodes
        assert self.total_producers <= 26


    def bootstrap(self):
        """
        Bootstrap
        ---------
        1. launch a cluster
        2. get cluster info
        3. create bios account
        4. schedule protocol feature activations
        5. set eosio.token contract
        6. create tokens
        7. issue tokens
        8. set system contract
        9. init system contract
        10. create producer accounts
        11. register producers
        12. vote for producers
        13. verify head producer
        """

        # print configuration
        self.print_config()

        # 1. launch a cluster
        self.launch_cluster()

        # 2. get cluster info
        self.get_cluster_info()

        # 3. create bios accounts
        self.create_bios_accounts()


    def print_config(self):
        self.print_header("cluster configuration")
        self.print_config_helper("-i: cluster_id",      HELP_CLUSTER_ID,        self.cluster_id,        DEFAULT_CLUSTER_ID)
        self.print_config_helper("-t: topology",        HELP_TOPOLOGY,          self.topology,          DEFAULT_TOPOLOGY)
        self.print_config_helper("-n: total_nodes",     HELP_TOTAL_NODES,       self.total_nodes,       DEFAULT_TOTAL_NODES)
        self.print_config_helper("-y: total_producers", HELP_TOTAL_PRODUCERS,   self.total_producers,   DEFAULT_TOTAL_PRODUCERS)
        self.print_config_helper("-z: producer_nodes",  HELP_PRODUCER_NODES,    self.producer_nodes,    DEFAULT_PRODUCER_NODES)
        self.print_config_helper("-u: unstarted_nodes", HELP_UNSTARTED_NODES,   self.unstarted_nodes,   DEFAULT_UNSTARTED_NODES)


    def launch_cluster(self, **kwargs):
        resp, tid = self.rpc("launch_cluster", cluster_id=self.cluster_id, node_count=self.total_nodes, shape=self.topology, nodes=self.nodes, **kwargs)
        return resp.text


    def get_cluster_info(self, **kwargs):
        resp, tid = self.rpc("get_cluster_info", cluster_id=self.cluster_id, **kwargs)
        return resp.text


    def create_bios_accounts(self, **kwargs):
        resp, tid = self.rpc("create_bios_accounts", cluster_id=self.cluster_id,
                                                     creator="eosio",
                                                     accounts=[{"name":"eosio.bpay"},
                                                               {"name":"eosio.msig"},
                                                               {"name":"eosio.names"},
                                                               {"name":"eosio.ram"},
                                                               {"name":"eosio.ramfee"},
                                                               {"name":"eosio.rex"},
                                                               {"name":"eosio.saving"},
                                                               {"name":"eosio.stake"},
                                                               {"name":"eosio.token"},
                                                               {"name":"eosio.upay"}],
                                                     **kwargs)
        return resp.text


    # def verify_transaction(self, transaction_id, node_id=0, quiet=False):
    #     resp, tid = self.call("verify_transaction", cluster_id=self.cluster_id, node_id=node_id, transaction_id=transaction_id, quiet=quiet)
    #     return helper.extract(resp, "irreversible", False)


    def rpc(self, endpoint: str, header: str =None, retry=5, wait=1, quiet=False, **data):
        if quiet:
            return self.quiet_rpc(endpoint=endpoint, retry=retry, wait=wait, **data)
        else:
            return self.loud_rpc(endpoint=endpoint, header=header, retry=retry, wait=wait, **data)


    def loud_rpc(self, endpoint: str, header: str =None, retry=5, wait=1, validate=False, **data):
        header = endpoint.replace("_", " ") if header is None else header
        self.print_header(header)
        ix = Interaction(endpoint, self.service, data)
        self.print_request(ix)
        while not ix.response.ok and retry > 0:
            self.print.red(ix.response)
            self.print.vanilla("Retrying ...")
            time.sleep(wait)
            ix.attempt()
            retry -= 1
        self.print.response(ix.response)
        assert ix.response.ok
        if validate:
            assert self.verify(ix.transaction_id)
        return ix.response, ix.transaction_id


    def quiet_rpc(self, endpoint: str, retry=5, wait=1, **data):
        ix = Interaction(endpoint, self.service, data)
        while not ix.response.ok and retry > 0:
            self.print.red(ix.response)
            self.print.vanilla("Retrying ...")
            time.sleep(wait)
            ix.attempt()
            retry -= 1
        assert ix.response.ok
        return ix.response, ix.transaction_id


    def print_request(self, ix):
        self.print.vanilla(ix.request.url)
        self.print.json(ix.request.data)


    # def verify(self, transaction_id: str, retry=5, wait=0.5) -> bool:
    #     verified = False
    #     while not verified and retry >= 0:
    #         self.print.vanilla("{:100}".format("Verifying ..."))
    #         verified = self.verify_transaction(cluster_id=self.cluster_id, node_id=0, transaction_id=tid)
    #         # verified = self.verify_transaction(**dict(cluster_id=self.cluster_id, node_id=0, transaction_id=tid))
    #         retry -= 1
    #         time.sleep(wait)
    #     if verified:
    #         self.print.decorate("Success!", fcolor="black", bcolor="green")
    #     else:
    #         self.print.decorate("Failure!", fcolor="black", bcolor="red")
    #     return verified
    #     # assert verified, self.alert.red("Failed to verify transaction ID {}".format(tid))





class Request:
    def __init__(self, url: str, data: str):
        self.url = url
        self.data = data

    def post(self):
        return requests.post(self.url, data=self.data)




class Interaction:
    def __init__(self, endpoint, service, data: dict, dont_attempt=False):
        self.request = Request(self.get_url(endpoint, service.address, service.port), json.dumps(data))
        if not dont_attempt:
            self.attempt()


    def attempt(self):
        self.response = self.request.post()
        self.transaction_id = helper.extract(self.response, key="transaction_id", fallback=None)
        return self.response, self.transaction_id


    @staticmethod
    def get_url(endpoint, address, port):
        return "http://{}:{}/v1/launcher/{}".format(address, port, endpoint)




def test():
    args = CommandLineArguments("service", "cluster")
    serv = Service(args=args)
    clus = Cluster(service=serv, args=args)


if __name__ == "__main__":
    test()
