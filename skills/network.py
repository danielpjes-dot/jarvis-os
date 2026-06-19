import socket
import threading
from typing import List, Tuple


def scan_network(network: str, timeout: float = 1.0) -> List[Tuple[str, int]]:
    """
    Scan a network for active hosts.
    
    Args:
        network: Network address in CIDR format (e.g., '192.168.1.0/24')
        timeout: Timeout for socket connections in seconds
    
    Returns:
        List of tuples (host, port) for active hosts
    """
    active_hosts = []
    
    # Parse network address (simplified for this example)
    # In a real implementation, you'd parse the CIDR properly
    base_ip = network.split('/')[0]
    ip_parts = base_ip.split('.')
    
    # Simple approach: scan first 255 IPs in the network
    for i in range(1, 255):
        ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.{i}"
        
        # Create thread for each host scan
        thread = threading.Thread(target=scan_host, args=(ip, timeout, active_hosts))
        thread.daemon = True
        thread.start()
        
    # Wait for all threads to complete
    # Note: In a production environment, you'd want better thread management
    
    return active_hosts


def scan_host(host: str, timeout: float, active_hosts: List[Tuple[str, int]]) -> None:
    """
    Scan a single host for open ports.
    
    Args:
        host: IP address to scan
        timeout: Timeout for socket connections
        active_hosts: List to append active hosts to
    """
    try:
        # Create socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        
        # Test common ports
        common_ports = [22, 80, 443, 8080, 3000]
        
        for port in common_ports:
            try:
                result = sock.connect_ex((host, port))
                if result == 0:
                    # Port is open
                    active_hosts.append((host, port))
                    break  # Found an open port, no need to check others
            except Exception:
                # Connection failed, continue to next port
                continue
                
    except Exception as e:
        # Handle any unexpected errors during host scanning
        print(f"Error scanning host {host}: {e}")
        return
    finally:
        try:
            sock.close()
        except:
            pass


def check_connection(host: str, port: int, timeout: float = 5.0) -> bool:
    """
    Check if a connection can be made to a host and port.
    
    Args:
        host: Host address
        port: Port number
        timeout: Connection timeout in seconds
    
    Returns:
        True if connection successful, False otherwise
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception as e:
        print(f"Connection error to {host}:{port}: {e}")
        return False