<div align="center">

<h1> YOLO Object Detection in ROS2 for Saaki - Unitree G1 </h1>

[![ROS 2 Humble](https://img.shields.io/badge/ROS2-Humble-22314E?logo=ros&logoColor=white)](https://docs.ros.org/en/humble/index.html)
[![Ubuntu 22.04](https://img.shields.io/badge/Ubuntu-22.04-E95420?logo=ubuntu&logoColor=white)](https://releases.ubuntu.com/22.04/)
[![Python 3.10](https://img.shields.io/badge/Python-3.10-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Ultralytics](https://img.shields.io/badge/Ultralytics-YOLO%20V8-111F68?logo=ultralytics&logoColor=white)](https://docs.ultralytics.com/models/yolov8/)
[![CUDA](https://img.shields.io/badge/CUDA-76B900?logo=nvidia&logoColor=white)](https://developer.nvidia.com/cuda/toolkit)

[![Computer Vision](https://img.shields.io/badge/AI-Computer%20Vision-purple)](https://www.ultralytics.com/)
[![Robot: Unitree G1](https://img.shields.io/badge/Robot-Unitree%20G1-0A66C2)](#-real-g1-robot)
[![Status: Tested on G1](https://img.shields.io/badge/Status-Tested%20on%20Real%20Hardware-success)](#execution-and-verification)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
</div>


## 📖 Description

This repository is a ROS 2 package for object detection on the **Unitree G1** using YOLO on the robot's official camera channel (`videohub`).

It publishes detections in standard ROS vision format (`vision_msgs/Detection2DArray`) and, optionally, annotated image and legacy JSON output.

**Credits and origin:** this package integrates with Unitree's official message layer (`unitree_api`, `unitree_go`, `unitree_hg`) and is designed to work with `unitree_ros2`.

Functional flow:

1. Sends requests to `/api/videohub/request` (`api_id=1001`).
2. Receives JPEG from `/api/videohub/response`.
3. Decodes frame with OpenCV.
4. Executes YOLO (`ultralytics`).
5. Publishes:
   - `/g1/yolo/detections_2d` (`vision_msgs/msg/Detection2DArray`)
   - `/g1/yolo/annotated_image` (`sensor_msgs/msg/Image`, optional)
   - `/g1/yolo/detections` (`std_msgs/msg/String`, optional JSON)

Design notes:

- Only **one request in flight** to avoid backlog.
- Has request timeout (`request_timeout_sec`) with automatic recovery.
- `device=auto` uses `cuda:0` if GPU is available; otherwise, `cpu`.
- Does not depend on `realsense-ros`.

---

## 🛠️ Prerequisites

- Ubuntu 22.04
- ROS 2 Humble
- Unitree G1 robot connected via Ethernet
- Operational Unitree underlay (`~/unitree_ros2/setup.sh`)

System dependencies:

```bash
sudo apt update
sudo apt install -y \
  ros-humble-vision-msgs \
  python3-opencv \
  python3-numpy
```

Python dependencies:

```bash
pip install ultralytics
```

---

## 📦 1. Base Installation (Unitree Dependencies)

Since this package depends on the robot's official messages (`unitree_go`, `unitree_hg`, `unitree_api`), it is **mandatory** to install and compile the official Unitree repository as the base layer ("underlay") before compiling this repository.

### 1.1. Install CycloneDDS

The robot communicates via CycloneDDS. In ROS 2 Humble, simply install the system binaries:

```bash
sudo apt install ros-humble-rmw-cyclonedds-cpp ros-humble-rosidl-generator-dds-idl libyaml-cpp-dev
```

### 1.2. Clone and compile official messages
It is not necessary to compile the entire Unitree repository, only its CycloneDDS workspace:

```bash
# Clone the official repository in your home directory (use our fork)
git clone https://github.com/UAI-BIOARABA/unitree_ros2

# Compile message packages
cd ~/unitree_ros2/cyclonedds_ws
colcon build
```

---

## 🎁 2. Installation and compilation of this repository

From your workspace:

```bash
cd ~/ros2_ws/src
# Clone this repository (we use '_' instead of '-' following ROS2 standards)
git clone https://github.com/UAI-BIOARABA/saaki-ros2-yolo.git saaki_ros2_yolo
# Go to workspace root
cd ~/ros2_ws
source /opt/ros/humble/setup.bash
source ~/unitree_ros2/setup.sh
colcon build --packages-select saaki_ros2_yolo
source ~/ros2_ws/install/setup.bash
```

---

## 🌐 3. Network Configuration (Robot Connection)

For ROS 2 to discover the robot, your PC must be on the same subnet and use CycloneDDS correctly.

### 1. Connect your PC to the robot via Ethernet cable.

### 2. Configure a static IP on your PC:

   - IP: 192.168.123.99

   - Netmask: 255.255.255.0

### 3. Edit the official configuration script (~/unitree_ros2/setup.sh). It should look something like this (change enp44s0 to your network interface name):

```sh
#!/bin/bash
echo "Setup unitree ros2 environment"
source /opt/ros/humble/setup.bash
source $HOME/unitree_ros2/cyclonedds_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces>
                            <NetworkInterface name="enp44s0" priority="default" multicast="default" />
                        </Interfaces></General></Domain></CycloneDDS>'
```

---

<a id="execution-and-verification"></a>

## 🚀 4. Execution and Verification

### Terminal 1: Launch

```bash
source /opt/ros/humble/setup.bash
source ~/unitree_ros2/setup.sh
source ~/ros2_ws/install/setup.bash

ros2 launch saaki_ros2_yolo saaki_ros2_yolo.launch.py
```

### Terminal 2: Detections (--once for single sample) and frequency

```bash
source /opt/ros/humble/setup.bash
source ~/unitree_ros2/setup.sh
source ~/ros2_ws/install/setup.bash

ros2 topic echo /g1/yolo/detections_2d --once
```

Legacy JSON output:

```bash
ros2 topic echo /g1/yolo/detections --once
```

Frequency:

```bash
ros2 topic hz /g1/yolo/detections_2d
```

### Terminal 3: Visualization

```bash
source /opt/ros/humble/setup.bash
source ~/unitree_ros2/setup.sh
source ~/ros2_ws/install/setup.bash

rviz2
```

Go to add -> by topic -> g1/yolo/annotated_image -> image.

`rqt_image_view` may be too slow, which is why we use RViz2.

---

## 💡 Package Topics

Input:

- `/api/videohub/request` (`unitree_api/msg/Request`)
- `/api/videohub/response` (`unitree_api/msg/Response`)

Output:

- `/g1/yolo/detections_2d` (`vision_msgs/msg/Detection2DArray`)
- `/g1/yolo/annotated_image` (`sensor_msgs/msg/Image`)
- `/g1/yolo/detections` (`std_msgs/msg/String`)

---

## 🎛️ Parameters

### Communication and Capture

| Parameter | Default | Description |
| --- | --- | --- |
| `request_topic` | `/api/videohub/request` | Frame request topic |
| `response_topic` | `/api/videohub/response` | Response topic with JPEG |
| `video_api_id` | `1001` | Videohub API ID |
| `request_timeout_sec` | `0.5` | In-flight request timeout |
| `target_fps` | `15.0` | Target capture/inference FPS |
| `frame_id` | `g1_front_camera` | `frame_id` of published messages |

### Output

| Parameter | Default | Description |
| --- | --- | --- |
| `detections_topic` | `/g1/yolo/detections_2d` | Main detection topic |
| `annotated_image_topic` | `/g1/yolo/annotated_image` | Annotated image topic |
| `publish_annotated_image` | `true` | Enable/disable annotated image |
| `annotated_image_max_fps` | `15.0` | Annotated image FPS limit (`0.0` for no limit) |
| `annotated_image_scale` | `0.33` | Annotated image scale |
| `publish_legacy_json` | `true` | Enable legacy JSON output |
| `legacy_detections_topic` | `/g1/yolo/detections` | Legacy JSON topic |

### YOLO Model

| Parameter | Default | Description |
| --- | --- | --- |
| `model_path` | `yolov8n.pt` | YOLO model (`.pt` or name) |
| `device` | `auto` | `auto`, `cpu`, `cuda:0`, etc. |
| `conf_threshold` | `0.25` | Confidence threshold |
| `iou_threshold` | `0.45` | IoU threshold for NMS |
| `max_detections` | `50` | Maximum detections per frame |

---

## ⚠️ Troubleshooting

`vision_msgs` not installed:

```bash
sudo apt install ros-humble-vision-msgs
```

`ultralytics` not installed:

```bash
pip install ultralytics
```

No frames arriving or no detections:

- Check `/ros_bridge`.
- Check `/api/videohub/request` and `/api/videohub/response`.
- Make sure you ran `source ~/unitree_ros2/setup.sh`.
- Check network (same subnet, correct interface in CycloneDDS).

Slow annotated image:

- Lower `annotated_image_scale` (`0.33 -> 0.25`).
- Keep `annotated_image_max_fps` between `10` and `15`.
- If you prioritize inference, disable annotated image.

---

## 🧑‍💻 Authors

- **Project Manager:** [Juan Fernández](https://github.com/jfbioaraba)
- **Lead Developer:** [Andoni González](https://github.com/andoni92)

---
## Disclaimer

This software and associated materials are provided "as is", without warranties of any kind, either express or implied, including—but not limited to—warranties of merchantability, fitness for a particular purpose, or freedom from errors.

The authors and Bioaraba – Instituto de Investigación Sanitaria assume no responsibility for the use, redistribution, or modification of this repository or for any direct or indirect damages arising from its use.

This project is intended exclusively for research and/or educational purposes.
