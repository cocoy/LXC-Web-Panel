from lxclite import exists, stopped, lxcdir
import subprocess
import os
import platform
import time
import ConfigParser
import re


class CalledProcessError(Exception):
    pass


class LxcConfigFileNotComplete(Exception):
    pass


class ContainerNotExists(Exception):
    pass


cgroup = {
    'type': 'lxc.network.type',
    'link': 'lxc.network.link',
    'flags': 'lxc.network.flags',
    'hwaddr': 'lxc.network.hwaddr',
    'rootfs': 'lxc.rootfs',
    'utsname': 'lxc.utsname',
    'arch': 'lxc.arch',
    'ipv4': 'lxc.network.ipv4',
    'memlimit': 'lxc.cgroup.memory.limit_in_bytes',
    'swlimit': 'lxc.cgroup.memory.memsw.limit_in_bytes',
    'cpus': 'lxc.cgroup.cpuset.cpus',
    'shares': 'lxc.cgroup.cpu.shares',
    'deny': 'lxc.cgroup.devices.deny',
    'allow': 'lxc.cgroup.devices.allow',
    'auto': 'lxc.start.auto'
}


class FakeSection(object):
    def __init__(self, fp):
        self.fp = fp
        self.sechead = '[DEFAULT]\n'

    def readline(self):
        if self.sechead:
            try:
                return self.sechead
            finally:
                self.sechead = None
        else:
            return self.fp.readline()


def del_section(filename=None):
    if filename:
        load = open(filename, 'r')
        read = load.readlines()
        load.close()
        i = 0
        while i < len(read):
            if '[DEFAULT]' in read[i]:
                del read[i]
                break
        load = open(filename, 'w')
        load.writelines(read)
        load.close()


def file_exist(filename):
    """
    checks if a given file exist or not
    """
    try:
        with open(filename) as f:
            f.close()
            return True
    except IOError:
        return False


def memory_usage(name):
    """
    returns memory usage in MB
    """
    if not exists(name):
        raise ContainerNotExists("The container (%s) does not exist!" % name)
    if name in stopped():
        return 0
    cmd = ['lxc-cgroup -n %s memory.usage_in_bytes' % name]
    try:
        out = subprocess.check_output(cmd, shell=True).splitlines()
    except OSError:
        return 0
    return int(out[0]) / 1024 / 1024


def host_memory_usage():
    """
    returns a dict of host memory usage values
                    {'percent': int((used/total)*100),
                    'percent_cached':int((cached/total)*100),
                    'used': int(used/1024),
                    'total': int(total/1024)}
    """
    total = free = buffers = cached = 0
    out = open('/proc/meminfo')
    for line in out:
        if 'MemTotal:' == line.split()[0]:
            split = line.split()
            total = float(split[1])
        if 'MemFree:' == line.split()[0]:
            split = line.split()
            free = float(split[1])
        if 'Buffers:' == line.split()[0]:
            split = line.split()
            buffers = float(split[1])
        if 'Cached:' == line.split()[0]:
            split = line.split()
            cached = float(split[1])
    out.close()
    used = (total - (free + buffers + cached))
    return {'percent': int((used / total) * 100),
            'percent_cached': int((cached / total) * 100),
            'used': int(used / 1024),
            'total': int(total / 1024)}


def host_cpu_percent():
    """
    returns CPU usage in percent
    """
    f = open('/proc/stat', 'r')
    line = f.readlines()[0]
    data = line.split()
    previdle = float(data[4])
    prevtotal = float(data[1]) + float(data[2]) + float(data[3]) + float(data[4])
    f.close()
    time.sleep(0.1)
    f = open('/proc/stat', 'r')
    line = f.readlines()[0]
    data = line.split()
    idle = float(data[4])
    total = float(data[1]) + float(data[2]) + float(data[3]) + float(data[4])
    f.close()
    intervaltotal = total - prevtotal
    percent = 100 * (intervaltotal - (idle - previdle)) / intervaltotal
    return str('%.1f' % percent)


def host_disk_usage(partition=None):
    """
    returns a dict of disk usage values
                    {'total': usage[1],
                    'used': usage[2],
                    'free': usage[3],
                    'percent': usage[4]}
    """
    if not partition:
        partition = '/'
    usage = subprocess.check_output(['df -h %s' % partition], shell=True).split('\n')[1].split()
    return {'total': usage[1],
            'used': usage[2],
            'free': usage[3],
            'percent': usage[4]}


def host_uptime():
    """
    returns a dict of the system uptime
            {'day': days,
            'time': '%d:%02d' % (hours,minutes)}
    """
    f = open('/proc/uptime')
    uptime = int(f.readlines()[0].split('.')[0])
    minutes = uptime / 60 % 60
    hours = uptime / 60 / 60 % 24
    days = uptime / 60 / 60 / 24
    f.close()
    return {'day': days,
            'time': '%d:%02d' % (hours, minutes)}


def check_ubuntu():
    """
    return the System version
    """
    dist = '%s %s' % (platform.linux_distribution()[0], platform.linux_distribution()[1])

    supported_dists = ['Ubuntu 12.04',
                       'Ubuntu 12.10',
                       'Ubuntu 13.04',
                       'Ubuntu 13.10',
                       'Ubuntu 14.04']

    if dist in supported_dists:
        return dist
    return 'unknown'


def get_templates_list():
    """
    returns a sorted lxc templates list
    """
    templates = []

    try:
        path = os.listdir('/usr/share/lxc/templates')
    except OSError:
        path = os.listdir('/usr/lib/lxc/templates')

    if path:
        for line in path:
                templates.append(line.replace('lxc-', ''))

    return sorted(templates)


def check_version():
    """
    returns latest LWP version (dict with current)
    """
    try:
        version = subprocess.check_output('git describe --tags', shell=True)
    except OSError:
        version = open('version').read()[0:-1]
    return {'current': version}


def get_net_settings():
    """
    returns a dict of all known settings for LXC networking
    """
    filename = '/etc/default/lxc-net'
    if not file_exist(filename):
        filename = '/etc/default/lxc'
    if not file_exist(filename):
        return False
    if check_ubuntu() == "unknown":
        raise LxcConfigFileNotComplete('This is not a Ubuntu distro ! Check if all config params are set in /etc/default/lxc')
    config = ConfigParser.SafeConfigParser()

    config.readfp(FakeSection(open(filename)))
    cfg = {
        'use': config.get('DEFAULT', 'USE_LXC_BRIDGE').strip('"'),
        'bridge': config.get('DEFAULT', 'LXC_BRIDGE').strip('"'),
        'address': config.get('DEFAULT', 'LXC_ADDR').strip('"'),
        'netmask': config.get('DEFAULT', 'LXC_NETMASK').strip('"'),
        'network': config.get('DEFAULT', 'LXC_NETWORK').strip('"'),
        'range': config.get('DEFAULT', 'LXC_DHCP_RANGE').strip('"'),
        'max': config.get('DEFAULT', 'LXC_DHCP_MAX').strip('"')
    }

    return cfg


def get_container_settings(name):
    """
    returns a dict of all utils settings for a container
    """
    filename = '{}/{}/config'.format(lxcdir(), name)
    if not file_exist(filename):
        return False
    config = ConfigParser.SafeConfigParser()
    cfg = {
        'type': '',
        'link': '',
        'flags': '',
        'hwaddr': '',
        'rootfs': '',
        'utsname': '',
        'arch': '',
        'ipv4': '',
        'memlimit': '',
        'swlimit': '',
        'cpus': '',
        'shares': '',
        'auto': False
    }
    config.readfp(FakeSection(open(filename)))

    for options in cfg.keys():
        if config.has_option('DEFAULT', cgroup[options]):
            cfg[options] = config.get('DEFAULT', cgroup[options])

    # if ipv4 is unset try to determinate it
    if cfg['ipv4'] == '':
        cmd = ['lxc-ls --fancy --fancy-format name,ipv4|grep \'^%s \'|egrep -o \'[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\'' % name]
        try:
            cfg['ipv4'] = subprocess.check_output(cmd, shell=True)
        except subprocess.CalledProcessError:
            pass

    # parse memlimits to int
    cfg['memlimit'] = re.sub(r'[a-zA-Z]', '', cfg['memlimit'])
    cfg['swlimit'] = re.sub(r'[a-zA-Z]', '', cfg['swlimit'])

    # parse auto to boolean
    cfg['auto'] = True if cfg['auto'] is '1' else False

    return cfg


def push_net_value(key, value, filename='/etc/default/lxc'):
    """
    replace a var in the lxc-net config file
    """
    if filename:
        config = ConfigParser.RawConfigParser()
        config.readfp(FakeSection(open(filename)))
        if not value:
            config.remove_option('DEFAULT', key)
        else:
            config.set('DEFAULT', key, value)

        with open(filename, 'wb') as configfile:
            config.write(configfile)

        del_section(filename=filename)

        load = open(filename, 'r')
        read = load.readlines()
        load.close()
        i = 0
        while i < len(read):
            if ' = ' in read[i]:
                split = read[i].split(' = ')
                split[1] = split[1].strip('\n')
                if '\"' in split[1]:
                    read[i] = '%s=%s\n' % (split[0].upper(), split[1])
                else:
                    read[i] = '%s=\"%s\"\n' % (split[0].upper(), split[1])
            i += 1
        load = open(filename, 'w')
        load.writelines(read)
        load.close()


def push_config_value(key, value, container=None):
    """
    replace a var in a container config file
    """

    def save_cgroup_devices(filename=None):
        """
        returns multiple values (lxc.cgroup.devices.deny and lxc.cgroup.devices.allow) in a list.
        because ConfigParser cannot make this...
        """
        if filename:
            values = []
            i = 0

            load = open(filename, 'r')
            read = load.readlines()
            load.close()

            while i < len(read):
                if not read[i].startswith('#') and \
                        re.match('lxc.cgroup.devices.deny|lxc.cgroup.devices.allow', read[i]):
                    values.append(read[i])
                i += 1
            return values

    if container:
        filename = '{}/{}/config'.format(lxcdir(), container)
        save = save_cgroup_devices(filename=filename)

        config = ConfigParser.RawConfigParser()
        config.readfp(FakeSection(open(filename)))
        if not value:
            config.remove_option('DEFAULT', key)
        elif key == cgroup['memlimit'] or key == cgroup['swlimit'] and value is not False:
            config.set('DEFAULT', key, '%sM' % value)
        else:
            config.set('DEFAULT', key, value)

        # Bugfix (can't duplicate keys with config parser)
        if config.has_option('DEFAULT', cgroup['deny']) or config.has_option('DEFAULT', cgroup['allow']):
            config.remove_option('DEFAULT', cgroup['deny'])
            config.remove_option('DEFAULT', cgroup['allow'])

        with open(filename, 'wb') as configfile:
            config.write(configfile)

        del_section(filename=filename)

        with open(filename, "a") as configfile:
            configfile.writelines(save)


def net_restart():
    """
    restarts LXC networking
    """
    cmd = ['/usr/sbin/service lxc-net restart']
    try:
        subprocess.check_call(cmd, shell=True)
        return 0
    except CalledProcessError:
        return 1