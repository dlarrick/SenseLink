import asyncio
import json
import time
import yaml
import argparse
from DataSource import *
from PlugInstance import *
from TPLinkEncryption import *
from aioudp import *
import nest_asyncio
nest_asyncio.apply()


# Check if a multi-layer key exists
def keys_exist(element, *keys):
    if not isinstance(element, dict):
        raise AttributeError('keys_exists() expects dict as first argument.')
    if len(keys) == 0:
        raise AttributeError('keys_exists() expects at least two arguments, one given.')

    _element = element
    for key in keys:
        try:
            _element = _element[key]
        except KeyError:
            return False
    return True


class SenseLink:
    _remote_ep = None
    _local_ep = None
    _instances = []
    should_respond = True

    def __init__(self, config, port=9999):
        self.config = config
        self.port = port
        self.server_task = None

    def create_instances(self):
        config = yaml.load(self.config, Loader=yaml.FullLoader)
        logging.debug(f"Configuration loaded: {config}")
        sources = config.get('sources')
        for source in sources:
            # Get specified identifier
            source_id = next(iter(source.keys()))
            logging.debug(f"Adding {source_id} configuration")
            # Static value plugs
            if source_id.lower() == "static":
                # Static sources require no extra config
                static = source['static']
                if static is None:
                    logging.error(f"Configuration error for Source {source_id}")
                # Generate plug instances
                plugs = static['plugs']
                instances = PlugInstance.configure_plugs(plugs, DataSource)
                self._instances.extend(instances)

            # HomeAssistant Plugs, using Websockets datasource
            elif source_id.lower() == "hass":
                # Configure this HASS Data source
                hass = source['hass']
                if hass is None:
                    logging.error(f"Configuration error for Source {source_id}")
                url = hass['url']
                auth_token = hass['auth_token']
                print(f"{url}, {auth_token}")
                ds_controller = HASSController(url, auth_token)

                # Generate plug instances
                plugs = hass['plugs']
                print("Generating instances")
                instances = PlugInstance.configure_plugs(plugs, HASSSource, ds_controller)

                # Add instances to self
                self._instances.extend(instances)

                # Start controller
                ds_controller.connect()

            else:
                logging.error(f"Source type {source_id} not recognized")

    def print_instance_wattages(self):
        for inst in self._instances:
            logging.info(f"Plug {inst.identifier} power: {inst.power}")

    async def start(self):
        self.create_instances()
        await self._serve()

    async def _serve(self):
        server_start = time()
        logging.info("Starting UDP server")
        self._local_ep = await open_local_endpoint('0.0.0.0', self.port)

        while True:
            data, addr = await self._local_ep.receive()
            request_addr = addr[0]
            decrypted_data = decrypt(data)

            try:
                json_data = json.loads(decrypted_data)
                # Sense requests the emeter and system parameters
                if keys_exist(json_data, "emeter", "get_realtime") and keys_exist(json_data, "system", "get_sysinfo"):
                    # Check for non-empty values, to prevent echo storms
                    if bool(safekey(json_data, 'emeter/get_realtime')):
                        # This is a self-echo, common with Docker without --net=Host!
                        logging.debug("Ignoring non-empty/non-Sense UDP request")
                        continue

                    logging.debug("Broadcast received from: %s: %s", request_addr, json_data)

                    if self._remote_ep is None:
                        self._remote_ep = await open_remote_endpoint(request_addr, self.port)

                    # Build and send responses
                    for inst in self._instances:
                        if inst.start_time is None:
                            inst.start_time = server_start
                        # Build response
                        response = inst.generate_response()
                        json_str = json.dumps(response, separators=(',', ':'))
                        encrypted_str = encrypt(json_str)
                        # Strip leading 4 bytes for...some reason
                        trun_str = encrypted_str[4:]

                        # Allow disabling response
                        if self.should_respond:
                            # Send response
                            logging.debug(f"Sending response: {response}")
                            self._remote_ep.send(trun_str)
                        else:
                            # Do not send response, but log for debugging
                            logging.debug(f"SENSE_RESPONSE disabled, response content: {response}")
                else:
                    logging.info(f"Unexpected/unhandled message: {json_data}")

            # Appears to not be JSON
            except ValueError:
                logging.debug("Did not receive valid json")
                return True


async def main():
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", help="specify config file path")
    parser.add_argument("-l", "--log", help="specify log level (DEBUG, INFO, etc)")
    parser.add_argument("-q", "--quiet", help="do not respond to Sense UPD queries", action="store_true")
    args = parser.parse_args()
    config_path = args.config or '/etc/senselink/config.yml'
    loglevel = args.log or 'WARNING'

    loglevel = os.environ.get('LOGLEVEL', loglevel).upper()
    logging.basicConfig(level=loglevel)

    # Assume config file is in etc directory
    config_location = os.environ.get('CONFIG_LOCATION', config_path)
    logging.debug(f"Using config at: {config_location}")
    config = open(config_location, 'r')

    # Create controller, with config
    controller = SenseLink(config)
    if os.environ.get('SENSE_RESPONSE', 'True').upper() == 'TRUE' or not args.quiet:
        logging.info("Will respond to Sense broadcasts")
        controller.should_respond = True

    # Start and run indefinitely
    logging.info("Starting SenseLink controller")
    loop = asyncio.get_event_loop()
    loop.create_task(controller.start())
    loop.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
