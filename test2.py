import netmiko 
from netmiko import ConnectHandler 
from colorama import init, Fore
import datetime
import os

init()

class Router:
    def __init__(self,device_info):
        self.device_info=device_info # device dict 
        self.host_address=device_info.get("ip" , "unknown device!")# bring host add from the dict host_addresses["ip"] if u dont find it print 'unknown device !'
        self.connection=None # the method that will connect us to the router
        

        self.Gater={}
        self.interfaces = {}
        self.pools = {}
        self.bindings = []
        self.relays = False
        self.routing_table = []

        self.conncetion_to_device()
        self.Gater_info()
        self.Parsing1()
    def conncetion_to_device(self):
        print(f"Connecting to {self.host_address}")
        try :
            self.connection=ConnectHandler(**self.device_info)
            print(f"Connection Succeeded to {self.host_address}")
        except Exception as e : 
            print(f"Connection Failed to {self.host_address} : {e}")
            raise
    def Gater_info(self):
        print("Gathering raw CLI data...")
        self.Gater["dhcp"] = self.connection.send_command('show run | sec dhcp')
        self.Gater["interface_brief"]=self.connection.send_command('show ip int bri')
        self.Gater["dhcp_bindidngs"]=self.connection.send_command('show ip dhcp binding')
        self.Gater["dhcp_relay"]=self.connection.send_command('show run | sec interface')
        self.Gater["show_ip_route"]=self.connection.send_command('show ip route | begin Gateway')
        self.Gater["hostname"]=self.connection.send_command("show run | include hostname")
    def hostname_device(self):
        output=self.Gater.get("hostname","").strip()
        if "hostname"  in output.lower() and "invalid" not in output.lower():
            h=output.split()
            return h[-1]
        else :
            return self.host_address

    def Parsing1(self):
        print("Parsing data into Python dictionaries...")
        self.routing_table=self.routing_table1(self.Gater["show_ip_route"])
        self.pools=self.detect_pools(self.Gater["dhcp"])
        self.bindings=self.bindings1(self.Gater["dhcp_bindidngs"])
        self.interfaces=self.intrf_info(self.Gater["interface_brief"])
        self.relays=self.relay_check(self.Gater["dhcp_relay"])
    def check_ip_add(self,add):
        parts=add.split(".")
        if len(parts)!=4:# ip add have 4 parts 
            return False 
        for part in parts:
            if not part.isdigit() :
                return False
            if int(part)>255 or int(part)<0 :
                return False 
        return True 
    def check_ip_in_pool(self,ip_with_mask,host_add):# takes pool network 192.168.100.0 255.255.255.0 and a host address 192.168.100.3 and tells you if the host add is in the pool network
        subnet_mask=0 
        broadcast_add=[0,0,0,0]
        net_index=0
        network_ip,mask=ip_with_mask.split()
        network_ip=network_ip.split('.')
        host_add=host_add.split('.')
        mask=mask.split('.')
        bits=[128,64,32,16,8,4,2,1]

        for i in range(len(network_ip)):
            network_ip[i]=int(network_ip[i])
            host_add[i]=int(host_add[i])
            mask[i]=int(mask[i])
        for element in mask:
            for bit in bits:
                if element-bit>=0:
                    subnet_mask+=1
                    element-=bit
                
        if subnet_mask%8==0:
            net_index=subnet_mask//8
            for i in range(net_index):
                broadcast_add[i]=network_ip[i]
            for i in range(1,4-net_index+1):# is this line good ? 
                broadcast_add[-i]=255
            block_size=256
        else:
            net_index=subnet_mask//8 
            rest=subnet_mask%8
            block_size=256-mask[net_index]
            for i in range(net_index):
                broadcast_add[i]=network_ip[i]
            broadcast_add[net_index]=network_ip[net_index]+block_size-1
            for i in range(net_index+1,4):
                broadcast_add[i]=255


        if network_ip == host_add:
            return False
        if broadcast_add == host_add:
            return False
        for octet in range(len(network_ip)):
            if network_ip[octet]>host_add[octet]:
                return False
            if broadcast_add[octet]<host_add[octet]:
                return False

        return True 
    def check_ip_in_pool2(self,pools,interfaces):
           result=[]
           if not pools:
                  return result
           else:
                  for pool_name , pool_val in pools.items():
                         p1=pool_val["network"]
                         if not p1:
                                continue
                         else:
                                for interface,interface_opt in interfaces.items():
                                       int1=interface_opt["ip address"]
                                       if int1=='unassigned':
                                              continue
                                       if self.check_ip_in_pool(p1,int1):
                                              result.append( f"Serving local clients on{Fore.GREEN} {interface} ({int1}) via {pool_name} : {p1} {Fore.RESET}")
           return result# extract pools and interface addresses and use check_ip_in_pool to return a list with the interfaces that belong to the pools 
    def relay_check(self,show_run_sec_interfaces):# check if the router is a dhcp relay
           interfaces={}
           
           x=show_run_sec_interfaces.splitlines()
           current_int=None
           for line in x:
                  if not line: 
                         continue 
                  line=line.strip()
                  if line.startswith("interface "):
                         current_int=line.split()[1]
                         interfaces[f"{current_int}"]=[]
                         
                  else :
                         interfaces[f"{current_int}"].append(line) 
           relay_agents=[]
           for inter , inter_info in interfaces.items():
                  for item in inter_info:
                         if "ip helper-address" in item:
                                item=item.split()
                                relay_agents.append(f'interface {inter} is a relay agent sending dhcp msgs to {item[-1]}')
           if relay_agents:
                  return relay_agents
           else:
                  return False
    def intrf_info(self,show_ip_int_bri):# returns a dict with interfaces info 
        lines=show_ip_int_bri.splitlines()
        int_db={}
        for line in lines :
            if line.startswith('Interface') or not line : continue 
            parts=line.split()
            if len(parts)<6:
                print("SKIPPING CORRUPTED LINE ")
                continue
            int_db[parts[0]]={'ip address':parts[1] ,
            "OK?":parts[2],
            "Method":parts[3],
            "Status":" ".join(parts[4:-1]),
            "Protocol":parts[-1]}
        return int_db
    def detect_pools(self,info_from_show_run_dhcp_section):# returns pools info 
        if not info_from_show_run_dhcp_section:
            print("WE DON'T HAVE ANY POOLS IN THE ROUTER")
            all_pools={}
            return all_pools
        else:
            lines=info_from_show_run_dhcp_section.splitlines()
            all_pools={}
            current_pool=None # this is our bookmark

            for line in lines:
                line=line.strip() # to remove leading/trailing spaces 
                if not line : continue 

                #1.Detect a new pool header 
                if line.startswith('ip dhcp pool'):
                    parts=line.split(maxsplit=3)
                    pool_name=parts[3]
                    current_pool=pool_name
                    all_pools[current_pool]={}
                elif current_pool:
                    key,value=line.split(maxsplit=1)
                    all_pools[current_pool][key]=value
            
        return all_pools
    def bindings1(self,show_ip_dhcp_bindings):# returns bindings info
        list_of_bindings=[]
        bindings_lines=show_ip_dhcp_bindings.splitlines()# this line go away because it depend on one example , we should start at the 1st ip add 
        element={}
        for line in bindings_lines:
            parts=line.split()
            if not parts:# if the part is empty skip the line 
                continue
            if  self.check_ip_add(parts[0]):# if the ip add is valid 
                if  element: # if the element dict have something in it 
                    list_of_bindings.append(element) # add it to the list of dicts the one we're going to return 
                element={} # start with an empty element dict 
                element["ip"]=parts[0]
                element["MAC-ADDRESS"]=parts[1]
                element["lease_expiration"]=' '.join(parts[2:7])
                rest_of_elements=parts[7:]
                if len(rest_of_elements)==1: # if we have one element left it is type no doubt 
                    element["type"]=rest_of_elements[0]
                elif len(rest_of_elements)==3:# if we have 3 elements left then its type , state and interface 
                    element["type"]=rest_of_elements[0]
                    element["state"]=rest_of_elements[1]
                    element["Interface"]=rest_of_elements[2]
                    
                
                    
            else:# if the ip add is not valid means our line don't start with an ip add 
                if element:# if the element dict have something add it to the element's mac address key in the dict 
                    element["MAC-ADDRESS"]+=parts[0]

        if element:
            list_of_bindings.append(element)

        return list_of_bindings 
    def ghost_interfaces(self,int_db):
        ghosted_interfaces=[]
        ghosted_interfaces_dict=[]
        for interface,info in int_db.items():
            if info["ip address"]!="unassigned" and not (info["Status"]=="up" and info["Protocol"]=="up"):
                ghosted_interfaces.append(f" Interface {interface} : {info['ip address']} ===> GHOSTED BCZ OF : Status:{info['Status']}  Protocol:{info['Protocol']} ")

                ghosted_interfaces_dict.append({ # this list of dicts for in case of future use of the ghosted interfaces 
                    "Interface":interface,
                    "Ip address":info["ip address"],
                    "Status":info["Status"],
                    "Protocol":info["Protocol"]
                    })
        return ghosted_interfaces

    def ip_with_subnet(self,ip_with_mask):# make 192.168.100.0 255.255.255.0 ==> 192.168.100.0/24
           subnet_mask=0 
           broadcast_add=[0,0,0,0]
           net_index=0
           network_ip,mask=ip_with_mask.split()
           IP=network_ip
           network_ip=network_ip.split('.')
           mask=mask.split('.')
           bits=[128,64,32,16,8,4,2,1]

           for i in range(len(network_ip)):
                  network_ip[i]=int(network_ip[i])
                  mask[i]=int(mask[i])
           for element in mask:
                  for bit in bits:
                         if element-bit>=0:
                                subnet_mask+=1
                                element-=bit
           return IP+'/'+str(subnet_mask)
    def routing_table1(self,show_ip_route):
           roads=[]
           rtl=show_ip_route.splitlines()
           for line in rtl:
                  if not line:
                         continue
                  elif "Gateway of last" in line:
                         continue
                  elif "is variably subnetted" in line:
                         continue
                  elif line.startswith("L"):
                         continue
                  elif "is subnetted," in line : 
                         continue
                  else:
                         road={}
                         parts= line.split()
                         road["code"]=parts[0]
                         road["address"]=parts[1]
                         if not self.check_ip_add(parts[-1]):
                                road["interface"]=parts[-1]
                         else:
                                road["next_hop"]=parts[-1]
                  roads.append(road)
           return roads
    def check_routing_table(self,routing_table,pools):# return matches list with notes about weather out dhcp clients are on a remote net or local
           matches=[]
           for pool_name , pool_info in pools.items():
                  pool_ip , pool_mask = pool_info["network"].split()
                  #print(pool_ip)
                  if pool_info["network"]:
                         sub_pool=self.ip_with_subnet(pool_info["network"])
                         for i in range(len(routing_table)):
                                if routing_table[i]["address"]==sub_pool:
                                       if routing_table[i]["code"]=='C':
                                              matches.append(f"The pool {Fore.LIGHTYELLOW_EX}{pool_name} {Fore.RESET}is serving dhcp on the local netowrk{Fore.LIGHTYELLOW_EX} {sub_pool} {Fore.RESET}via interface{Fore.LIGHTYELLOW_EX} {routing_table[i]['interface']}{Fore.RESET}")

                                       else:
                                              matches.append(f"The pool {Fore.LIGHTYELLOW_EX}{pool_name} {Fore.RESET}is serving dhcp on a remote netowrk {Fore.LIGHTYELLOW_EX}{sub_pool} {Fore.RESET}via interface {Fore.LIGHTYELLOW_EX}{routing_table[i]['interface']}{Fore.RESET}")
                                elif routing_table[i]["address"]==pool_ip:
                                        matches.append(f"The pool {Fore.LIGHTYELLOW_EX}{pool_name} {Fore.RESET}is serving dhcp on a remote netowrk {Fore.LIGHTYELLOW_EX}{sub_pool}{Fore.RESET} via  {Fore.LIGHTYELLOW_EX}{routing_table[i]['next_hop']}{Fore.RESET}")

                  else:
                         continue
           return matches   
    def octet_to_num(self,ip):
       octe=ip.split(".")
       return ((int(octe[0])<<24) + (int(octe[1])<<16)+(int(octe[2])<<8)+(int(octe[3])))
    def detect_excluded(self): # returns a dict with pool name and number of excluded addresses {'R1_lan_Farm': 17, 'lan25': 6, 'Caica_network': 0}
           # work with pool_utilization()
           excluded_addresses={pool_name : 0 for pool_name in self.pools}
           for line in self.Gater["dhcp"].splitlines():
                  line=line.strip()
                  if not line:
                         continue
                  if line.startswith('ip dhcp excluded-address'):
                         excluded_line=line.split()
                         if len(excluded_line)==4:
                                for pool_name, pool_data in self.pools.items():
                                       if self.check_ip_in_pool(pool_data["network"],excluded_line[-1]):
                                              excluded_addresses[pool_name]=excluded_addresses.get(pool_name,0) +1 
                         elif len(excluded_line)==5:
                                first_num=excluded_line[-2]
                                second_num=excluded_line[-1]
                                count=self.octet_to_num(second_num) - self.octet_to_num(first_num)+1
                                for pool_name, pool_data in self.pools.items():
                                       if self.check_ip_in_pool(pool_data["network"],second_num):
                                              excluded_addresses[pool_name]=excluded_addresses.get(pool_name,0) + count


           return excluded_addresses
    def pool_utilization(self):
        excluded_dict = self.detect_excluded()
        pool_adresses = {}
        
        for pool_name, pool_data in self.pools.items():
            pool_address = pool_data.get('network', 'no network found')
            subnet_mask = 0
            networkip, mask = pool_address.split()
            network_ip = networkip.split('.')
            mask = mask.split('.')
            bits = [128, 64, 32, 16, 8, 4, 2, 1]

            for i in range(len(network_ip)):
                network_ip[i] = int(network_ip[i])
                mask[i] = int(mask[i])
                
            for element in mask:
                for bit in bits:
                    if element - bit >= 0:
                        subnet_mask += 1
                        element -= bit
            
            total_ips = (2**(32 - subnet_mask)) - 2
            
            leased_ips = 0
            for i in range(len(self.bindings)):
                if self.check_ip_in_pool(pool_address, self.bindings[i]["ip"]):
                    leased_ips += 1
            
            available_ips = total_ips - leased_ips - excluded_dict[f"{pool_name}"]
            used_ips = leased_ips + excluded_dict[f"{pool_name}"]
            
            pool_adresses[f"{pool_name}"] = {
                "network-ip": networkip,
                "total_ips": total_ips,
                "leased_ips": leased_ips,
                "excluded_addresses": excluded_dict[f"{pool_name}"],
                "available_ips": available_ips,
                "used_ips": used_ips
            }

        
        pool_util = ''
        for pool_name, pool_data in pool_adresses.items():
            percent = round((pool_data["used_ips"] / pool_data["total_ips"]) * 100)
            if percent <= 70:
                pool_util += f'{pool_name:<15}: {pool_data["network-ip"]:<16} ==> used {Fore.GREEN}{f"{percent}%":<5}{Fore.RESET}of the pool (available: {Fore.GREEN}{pool_data["available_ips"]:<4}{Fore.RESET} / total: {pool_data["total_ips"]:<4}add)  \n'
            elif percent > 70 and percent <= 90:
                pool_util += f'{pool_name:<15}: {pool_data["network-ip"]:<16} ==> used {Fore.LIGHTYELLOW_EX}{f"{percent}%":<5}{Fore.RESET}of the pool (available: {Fore.LIGHTYELLOW_EX}{pool_data["available_ips"]:<4}{Fore.RESET} / total: {pool_data["total_ips"]:<4}add)  \n'
            else:
                pool_util += f'{pool_name:<15}: {pool_data["network-ip"]:<16} ==> used {Fore.RED}{f"{percent}%":<5}{Fore.RESET}of the pool (available: {Fore.RED}{pool_data["available_ips"]:<4}{Fore.RESET} / total: {pool_data["total_ips"]:<4}add)  \n'
        
        return pool_util



    def interface_health_stat(self):
        output=[]
        output.append(f"{self.hostname_device():-^100}")
        output.append(f"{"INTERFACE HEALTH STATUS":-^100}")
        
        color=''
        reset = Fore.RESET
        unsued_int=0
        unused_int_list=[]
        for int_name,int_data in self.interfaces.items():
            if int_data["ip address"]=='unassigned' and (int_data["Method"]=='unset' or int_data["Method"]=="NVRAM"):
                color=Fore.MAGENTA
                unsued_int+=1
                unused_int_list.append(f'{int_name} ')
            if  int_data["ip address"]=='unassigned' and int_data["Status"]== "up" and int_data["Protocol"]=="up":
                color= Fore.BLUE
                output.append(f"{color}{int_name:<20}   {int_data['ip address']:<15}    {int_data['Method']:<15}    Acitve UP But NO IP ADD {reset} ")
            elif int_data["Status"]== "up" and int_data["Protocol"]=="up":
                color= Fore.GREEN 
                output.append(f"{color}{int_name:<20}   {int_data['ip address']:<15}    {int_data['Method']:<15}    Healthy{reset} ")
            elif int_data["Status"]== "down" and int_data["Protocol"]=="down":
                color= Fore.RED
                output.append(f"{color}{int_name:<20}   {int_data['ip address']:<15}    {int_data['Method']:<15}    Physical Issue{reset}")
            elif int_data["Status"]=="administratively down":
                color= Fore.MAGENTA
                output.append(f"{color}{int_name:<20}   {int_data['ip address']:<15}    {int_data['Method']:<15}    SHUT DOWN BY ADMIN{reset}")
            elif int_data["Status"]== "up" and int_data["Protocol"]=="down":
                color= Fore.LIGHTCYAN_EX
                output.append(f"{color}{int_name:<20}   {int_data['ip address']:<15}    {int_data['Method']:<15}    LAYER 2 ISSUE |Protocol Down{reset}")
        output.append(f'Unused Interfaces : {unsued_int} ')
        for inter in unused_int_list:
            color=Fore.CYAN
            output.append(f"{color}{inter:<30}{reset}")
        output='\n'.join(output)
        return output# this fct works with the return of the intrf_info

    def dhcp_server_status(self):
        color1=Fore.LIGHTYELLOW_EX
        pool_output=''
        local_servings=''
        bind_output = ""
        output_start=f"{'='*100}\n{f'DHCP STATUS for {self.hostname_device()}':~^100}\n{'='*100}\n"
        if len(self.pools)==0 and len(self.bindings)==0:
            color=Fore.RED
            
            report=f"No evidence that this device is a local DHCP server {color}(NOT DHCP DETECTED)\n NO POOL NO BINDINGS{Fore.RESET}\n"
            report+=f"\n\n{'RELAY DHCP INFO':~^100}\n"
            if self.relays:
                for relay in self.relays:
                    report+=f"The router is a {color1}DHCP relay \n{relay}{Fore.RESET}\n"
            else:
                report+=f"The router has no relay agents \n"
        elif len(self.pools)!=0 and len(self.bindings)==0:
            color=Fore.BLUE
            report = f"{color} DHCP server is configured , but no leases were found (CONFIGURED DHCP ){Fore.RESET}"
            lines_list=[]
            pool_output=''
            for pool_name , pool_options in self.pools.items():
                lines_list.append(f"{color}{'Pool name':<20}: {pool_name:<20}{Fore.RESET}")
                for key, value in pool_options.items():
                    line=f"{color}{key:<20}: {value:<20}{Fore.RESET}"
                    lines_list.append(line)
                lines_list.append(f"{color}={Fore.RESET}"*40)
            lines_list.pop()
            pool_output+='\n'.join(lines_list)

            routing_matches = self.check_routing_table(self.routing_table, self.pools)
            if routing_matches:
                pool_output+=f"\n\n{'LOCAL DHCP SERVINGS':~^100}\n"
                pool_output+="\n".join(routing_matches) 
            #================ pool utilization===========================
            pool_output+=f"\n\n{' DHCP CONSUMATION ':~^100}\n"
            pool_output+=f"\n{ self.pool_utilization()}\n"
            #================ RELAYS=========================== 
            pool_output+=f"\n\n{'RELAY DHCP INFO':~^100}\n"
            if self.relays:
                for relay in self.relays:
                    pool_output+=f"The router is a {color1}DHCP relay \n{relay}{Fore.RESET}\n"
            else:
                pool_output+=f"The router has no relay agents\n "

        elif len(self.pools)!=0 and len(self.bindings)!=0:
            color=Fore.GREEN
            report = f"DHCP server is active {color}(ACTIVE DHCP ){Fore.RESET}"
            lines_list=[]
            pool_output=f' {"POOLS":*^100} \n'
            for key,value in self.pools.items():
                lines_list.append(f"Pool's name : {key:<20} IP : {value['network']:<20}")
            pool_output+='\n'.join(lines_list)

            routing_matches = self.check_routing_table(self.routing_table, self.pools)
            if routing_matches:
                pool_output+=f"\n\n{'LOCAL DHCP SERVINGS':~^100}\n"
                pool_output+="\n".join(routing_matches)
            #================ pool utilization===========================
            pool_output+=f"\n\n{' DHCP CONSUMATION ':~^100}\n"
            pool_output+=f"\n{ self.pool_utilization()}\n"
            #=============== RELAYS==========================
            pool_output+=f"\n\n{'RELAY DHCP INFO':~^100}\n"
            if self.relays:
                for relay in self.relays:
                    pool_output+=f"The router is a {color1}DHCP relay \n{relay}{Fore.RESET}\n"
            else:
                pool_output+=f"The router has no relay agents \n"
            #============= bindings ============>>
            lines_list=[]

            bind_output=f'\n {"BINDINGS":*^100} \n'
            for i in range(len(self.bindings)):
                lines_list.append(f"Leased ip : {self.bindings[i]['ip']:<20} | expires : {self.bindings[i]['lease_expiration']:<20}")
            bind_output+='\n'.join(lines_list)
        elif len(self.pools)==0 and len(self.bindings)!=0:
            color=Fore.MAGENTA
            report = f"{color} DHCP bindings exist but NO DHCP pools were detected . INVESTIGATE (ANOMALY ){Fore.RESET}"
            report+=f"\n\n{'RELAY DHCP INFO':~^100}\n"
            
            if self.relays:
                for relay in self.relays:
                    report+=f"The router is a {color1}DHCP relay \n{relay}{Fore.RESET}\n"
            else:
                report+=f"The router has no relay agents \n"

        output_start+=report+"\n"
        output=output_start+"\n"+pool_output+"\n"+bind_output+"\n"
        return output

# R1={
#     'device_type':'cisco_ios',
#     'ip':'DEVICE IP',
#     'username':'YOUR_USERNAME',
#     'password':'YOUR_PASSWORD'
# }
# R2={
#     'device_type':'cisco_ios',
#     'ip':'DEVICE IP',
#     'username':'YOUR_USERNAME',
#     'password':'YOUR_PASSWORD'
# }
# devices = [R1, R2]


# folder_path = "C:\\PATH_TO_YOUR_DESIRED_FOLDER\\reports_from_dhcp_prog" # REPLACE WITH YOUR DESIRED FOLDER PATH
# os.makedirs(folder_path, exist_ok=True)

R1={
    'device_type':'cisco_ios',
    'ip':'12.12.12.1',
    'username':'walid',
    'password':'123 '
}
R2={
    'device_type':'cisco_ios',
    'ip':'192.168.52.148',
    'username':'walid',
    'password':'123'
}
devices = [R1, R2]

# Create folder
folder_path = "C:\\Users\\hp\\Desktop\\reports_from_dhcp_prog"# dir le path ta3k !!!!!!!!!!!!!!!
os.makedirs(folder_path, exist_ok=True)





timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
file_path = f"{folder_path}\\Network_Report_{timestamp}.html"


def ansi_to_html(text):
    color_map = {
        Fore.RED: '<span style="color: red;">',
        Fore.GREEN: '<span style="color: green;">',
        Fore.YELLOW: '<span style="color: #d4d400;">',
        Fore.BLUE: '<span style="color: blue;">',
        Fore.MAGENTA: '<span style="color: magenta;">',
        Fore.CYAN: '<span style="color: cyan;">',
        Fore.LIGHTCYAN_EX: '<span style="color: lightcyan;">',
        Fore.LIGHTYELLOW_EX: '<span style="color: #ffff00;">',
        Fore.RESET: '</span>',
    }
    

    for ansi_code, html_tag in color_map.items():
        text = text.replace(ansi_code, html_tag)
    
    return text


with open(file_path, "w", encoding="utf-8") as file:
    
    file.write("""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Network Report</title>
    <style>
        body {
            background-color: #1e1e1e;
            color: #d4d4d4;
            font-family: 'Consolas', 'Courier New', monospace;
            padding: 20px;
            line-height: 1.6;
        }
        pre {
            white-space: pre-wrap;
            word-wrap: break-word;
        }
    </style>
</head>
<body>
<pre>
""")
    
    for device in devices:

        try:
            my_router = Router(device)

            interface_report = ansi_to_html(my_router.interface_health_stat())
            dhcp_report = ansi_to_html(my_router.dhcp_server_status())
            
            file.write(interface_report + "\n\n")
            file.write(dhcp_report + "\n\n")
            
        except Exception as e:
            error_msg = f"Skipping device {device.get('ip', 'Unknown')} due to connection failure\n"
            error_msg += f"Actual error: {e}\n"
            file.write(error_msg)
            print(error_msg)
    
    
    file.write("</pre>\n</body>\n</html>")

print(f" Done! Saved to: {file_path}")