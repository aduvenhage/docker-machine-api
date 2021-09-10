import os


class DigitalOceanConfig:
    def __init__(self, token=None, region=None, type=None, image=None, docker_install=None):
        self._region = region or 'ams3'
        self._type = type or 's-1vcpu-2gb-amd'
        self._token = token or os.getenv('DO_API_TOKEN')
        self._image = image or 'ubuntu-18-04-x64'
        self._docker_install = docker_install or 'https://releases.rancher.com/install-docker/19.03.9.sh'

    def is_valid(self):
        return bool(self._token)

    def config(self):
        return {
            'driver': 'digitalocean',
            'digitalocean-region': self._region,
            'digitalocean-size': self._type,
            'digitalocean-image': self._image,
            'digitalocean-access-token': self._token,
            'engine-install-url': self._docker_install
        }


class AwsConfig:
    def __init__(self, access_key=None, secret_key=None, region=None, type=None, image=None):
        self._region = region or 'us-east-2'
        self._type = type or 't2.micro'
        self._access_key = access_key or os.getenv('AWS_ACCESS_KEY')
        self._secret_key = secret_key or os.getenv('AWS_SECRET_KEY')
        self._image = image or 'ami-0b9064170e32bde34'

    def is_valid(self):
        return bool(self._access_key) and bool(self._secret_key)

    def config(self):
        return {
            'driver': 'amazonec2',
            'amazonec2-access-key': self._access_key,
            'amazonec2-secret-key': self._secret_key,
            'amazonec2-region': self._region,
            'amazonec2-instance-type': self._type,
            'amazonec2-ami': self._image
        }
