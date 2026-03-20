# Setuptools configuration for the saaki_ros2_yolo ROS 2 package.
from glob import glob
import os

from setuptools import find_packages, setup

# Keep the package name in one place so install paths stay consistent.
package_name = "saaki_ros2_yolo"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        # Register the package with the ament index and install the launch/config
        # assets so `ros2 launch` can find them after installation.
        (
            "share/ament_index/resource_index/packages",
            [f"resource/{package_name}"],
        ),
        (f"share/{package_name}", ["package.xml", "README.md"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="bioar642",
    maintainer_email="andoni9292@gmail.com",
    description="YOLO-based object detection node for Unitree G1 camera streams via videohub API.",
    license="CC-BY-4.0",
    extras_require={
        "test": [
            "pytest",
        ],
    },
    entry_points={
        "console_scripts": [
            "saaki_ros2_yolo_node = saaki_ros2_yolo.yolo_detector_node:main",
        ],
    },
)
