from pathlib import Path
from collections import namedtuple
import aiofiles
import asyncio

import aiodocker
import os
import stat
import re
from prodict import Prodict
import ujson
import subprocess
from pprint import pprint
from band import logger
from .image_navigator import ImageNavigator
from .utils import underdict, tar_image_cmd, pack_ports, unpack_ports, def_labels, inject_attrs, short_info
"""
links:
http://aiodocker.readthedocs.io/en/latest/
https://docs.docker.com/engine/api/v1.37/#operation/ContainerList
https://docs.docker.com/engine/api/v1.24/#31-containers
"""

ImageObj = namedtuple('ImageObj', 'name category path')
img_cat = Prodict(user='user', collection='collection', base='base')


class Dock():
    """
    """

    def __init__(self, images, container_params, container_env, **kwargs):
        self.dc = aiodocker.Docker()
        self.imgnav = ImageNavigator(images)
        self.initial_ports = list(range(8900, 8999))
        self.available_ports = list(self.initial_ports)
        self.container_env = Prodict.from_dict(container_env)
        self.container_params = Prodict.from_dict(container_params)

    async def inspect_containers(self):
        await self.imgnav.load()
        conts = await self.containers()
        for cont in conts.values():
            await self.inspect_container(cont)
        return [short_info(cont) for cont in conts.values()]

    async def inspect_container(self, cont):
        logger.info(f"inspecting container {cont.attrs.name}")
        lbs = cont.attrs.labels
        for port in lbs.ports and unpack_ports(lbs.ports) or []:
            logger.info(f' -> {lbs.inband} port:{port}')
            self.allocate_port(port)

    async def conts_list(self):
        conts = await self.containers()
        return [short_info(cont) for cont in conts.values()]

    async def get(self, name):
        conts = await self.containers()
        return conts.get(name, None)

    async def containers(self):
        filters = ujson.dumps({'label': ['inband=inband']})
        conts = await self.dc.containers.list(all=True, filters=filters)
        for cont in conts:
            await cont.show()
        return {(cont.attrs.name): inject_attrs(cont) for cont in conts}

    def allocate_port(self, port=None):
        if port and port in self.available_ports:
            self.available_ports.remove(port)
            return port
        return self.available_ports.pop()

    async def remove_container(self, name):
        await self.stop_container(name)
        conts = await self.containers()
        if name in list(conts.keys()):
            logger.info(f"removing container {name}")
            await conts[name].delete()
        return True

    async def stop_container(self, name):
        conts = await self.containers()
        if name in list(conts.keys()):
            logger.info(f"stopping container {name}")
            await conts[name].stop()
            return True

    async def restart_container(self, name):
        conts = await self.containers()
        if name in list(conts.keys()):
            logger.info(f"restarting container {name}")
            await conts[name].restart()
            return True

    async def create_image(self, name, path):
        img_id = None
        path = Path(path).resolve()

        with subprocess.Popen(
                tar_image_cmd(path), stdout=subprocess.PIPE) as proc:
            img_params = Prodict.from_dict({
                'fileobj': proc.stdout,
                'encoding': 'identity',
                'tag': name,
                'labels': def_labels(),
                'stream': True
            })

            logger.info(f"building image {img_params} from {path}")
            async for chunk in await self.dc.images.build(**img_params):
                if isinstance(chunk, dict):
                    logger.debug(chunk)
                    if 'aux' in chunk:
                        img_id = underdict(chunk['aux'])
                else:
                    logger.debug('chunk: %s %s', type(chunk), chunk)
            logger.info('image created %s', img_id)

        img = await self.dc.images.get(name)
        return Prodict.from_dict(underdict(img))

    async def run_container(self, name, params):

        # build custom images
        if False:

            img_path = ''
        else:
            # rebuild base image
            await self.create_image(self.imgnav.base.name,
                                    self.imgnav.base.path)

        # service image
        
        img = await self.create_image(self.imgnav[name].name, self.imgnav[name].path)

        def take_port():
            return {
                'HostIp': self.container_params.bind_ip,
                'HostPort': str(self.allocate_port())
            }

        ports = {
            port: [take_port()]
            for port in img.container_config.exposed_ports.keys() or {}
        }
        a_ports = [port[0]['HostPort'] for port in ports.values()]

        env = {'NAME': name}
        env.update(self.container_env)

        config = Prodict.from_dict({
            'Image':
            img.id,
            'Hostname':
            name,
            'Cmd':
            name,
            'Ports':
            ports,
            'Labels':
            def_labels(a_ports=a_ports),
            'Env': [f"{k}={v}" for k, v in env.items()],
            'StopSignal':
            'SIGTERM',
            'HostConfig': {
                'RestartPolicy': {
                    'Name': 'unless-stopped'
                },
                'PortBindings': ports,
                'NetworkMode': self.container_params.network,
                'Memory': self.container_params.memory
            }
        })

        print(config)

        logger.info(f"starting container {name}. ports: {config.Ports}")
        c = await self.dc.containers.create_or_replace(name, config)
        await c.start()
        await c.show()
        c = inject_attrs(c)
        logger.info(f'started container {c.attrs.name} [{c.attrs.id}]')
        return short_info(c)
