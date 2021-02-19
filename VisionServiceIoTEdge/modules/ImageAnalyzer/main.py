# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for
# full license information.

import io
import os
import sys
import json
import time
import asyncio
import requests
from six.moves import input
from azure.iot.device import Message, MethodResponse
from azure.iot.device.aio import IoTHubModuleClient

COUNT = 0
DEBUG = bool(os.environ['DEBUG']) if "DEBUG" in os.environ else False
CAPTURE_INTERVAL = int(os.environ['CAPTURE_INTERVAL'])
CAMERA_CAPTURE_URL = os.environ['CAMERA_CAPTURE_URL']
COMPUTER_VISION_URL = os.environ['COMPUTER_VISION_URL']
COMPUTER_VISION_KEY = os.environ['COMPUTER_VISION_KEY']
CONFIDENCE_THRESHOLD = float(os.environ['CONFIDENCE_THRESHOLD'])

def set_camera_module(action):
    """Sets the camera module to start or stop"""

    endpoint = CAMERA_CAPTURE_URL + "/camera/" + action
    if DEBUG:
        print("Calling endpoint '%s'" % endpoint)

    response = requests.post(endpoint)
    
    if DEBUG:
        print("Call to endpoint '%s' returned status code %s. Reason: %s" % (endpoint, str(response.status_code), response.content))

def capture_image():
    """
    Makes an HTTP call to the camera module.
    Expects an image in octet-stream format
    """

    endpoint = CAMERA_CAPTURE_URL + "/camera/capture"
    if DEBUG:
        print("Calling endpoint '%s'" % endpoint)

    response = requests.get(endpoint)

    if response.status_code == 200:
        return response.content
    else:
        if DEBUG:
            print("Call to endpoint '%s' returned status code %s. Reason: %s" % (endpoint, str(response.status_code), response.content))
        return None

def tag_image(image):
    """
    Makes an HTTP call to the Computer Vision API.
    Sends an image in octect-stream format.
    Expects a Json object.
    """

    headers = {
        "Content-Type": "application/octet-stream",
        "Ocp-Apim-Subscription-Key": COMPUTER_VISION_KEY
    }

    endpoint = COMPUTER_VISION_URL + "/vision/v3.1/tag"
    if DEBUG:
        print("Calling endpoint %s" % endpoint)

    response = requests.post(endpoint, data=image, headers=headers)
    if response.status_code == 200:
        tags = json.loads(response.content)
        return tags['tags']
    else:
        if DEBUG:
            print("Call to endpoint '%s' returned status code %s. Reason: %s" % (endpoint, str(response.status_code), response.content))
        return None

async def main():

    global COUNT
    global CAPTURE_INTERVAL
    
    try:
        if not sys.version >= "3.5.3":
            raise Exception( "The sample requires python 3.5.3+. Current version of Python: %s" % sys.version )
        print ( "IoT Hub Client for Python" )

        # The client object is used to interact with your Azure IoT hub.
        module_client = IoTHubModuleClient.create_from_edge_environment(websockets=True)

        # connect the client.
        await module_client.connect()

        # define behavior for receiving direct methods
        async def method_request_handler(method_request):
            
            while True:
                print (
                    "\nMethod callback called with:\nmethodName = {method_name}\npayload = {payload}".format(
                        method_name=method_request.name,
                        payload=method_request.payload
                    )
                )
                if method_request.name == "SetCaptureInterval":
                    try:
                        CAPTURE_INTERVAL = int(method_request.payload)
                    except ValueError:
                        response_payload = {"Response": "Invalid parameter"}
                        response_status = 400
                    else:
                        response_payload = {"Response": "Executed direct method {}".format(method_request.name)}
                        response_status = 200
                else:
                    response_payload = {"Response": "Direct method {} not defined".format(method_request.name)}
                    response_status = 404

                # Send the response
                method_response = MethodResponse.create_from_method_request(method_request, status, payload)
                await module_client.send_method_response(method_response)

        # Set the method request handler on the client
        module_client.on_method_request_received = method_request_handler

        # define behavior for receiving a twin patch
        def twin_patch_handler(patch):
            print("the data in the desired properties patch was: {}".format(patch))

        # set the twin patch handler on the client
        module_client.on_twin_desired_properties_patch_received = twin_patch_handler

        # define behavior for receiving an input message on input1
        async def input1_listener(module_client):
            while True:
                input_message = await module_client.receive_message_on_input("input1")  # blocking call
                print("the data in the message received on input1 was ")
                print(input_message.data)
                print("custom properties are")
                print(input_message.custom_properties)
                print("forwarding mesage to output1")
                await module_client.send_message_to_output(input_message, "output1")

        # Schedule task for C2D Listener
        listeners = asyncio.gather(input1_listener(module_client))

        # define behavior for halting the application
        def stdin_listener():
            selection = input("Press Q to quit\n")
            while True:
                try:
                    # selection = input("Press Q to quit\n")
                    if selection == "Q" or selection == "q":
                        print("Quitting...")
                        break
                except:
                    time.sleep(10)

        # Run the stdin listener in the event loop
        loop = asyncio.get_event_loop()
        user_finished = loop.run_in_executor(None, stdin_listener)

        # Run endless loop for recurring tasks
        print ( "Module is running.")

        # Initialize camera module
        set_camera_module("start")

        while True:
            image = capture_image()
            if image:
                tags = tag_image(image)
                if tags:
                    if DEBUG:
                        print("Total tag count: %s" % str(len(tags)))

                    # Filter tags that meet the threshold criteria
                    tags = list(filter(lambda x: x['confidence'] >= CONFIDENCE_THRESHOLD, tags))
                    if DEBUG:
                        print("Total filtered tag count: %s" % str(len(tags)))

                    # Send tags to IoT Hub
                    if tags:
                        message = Message(json.dumps({"tags": tags}), content_encoding="utf-8", content_type="application/json")
                        await module_client.send_message_to_output(message, "output1")
                else:
                    print("Failed to tag image")
            else:
                print("Failed to get image from camera module")

            COUNT += 1
            if DEBUG:
                print("COUNT: %s" % str(COUNT))

            time.sleep(CAPTURE_INTERVAL)

        # Wait for user to indicate they are done listening for messages
        await user_finished

        # Cancel listening
        listeners.cancel()

        # Finally, disconnect
        await module_client.disconnect()

    except Exception as e:
        print ( "Unexpected error %s " % e )
        raise

if __name__ == "__main__":
    # loop = asyncio.get_event_loop()
    # loop.run_until_complete(main())
    # loop.close()

    # If using Python 3.7 or above, you can use following code instead:
    asyncio.run(main())