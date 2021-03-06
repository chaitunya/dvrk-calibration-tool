from __future__ import print_function, division
import sys
import os.path
import time
import numpy as np
import PyKDL
import rospy
from recording import Recording
from marker import Marker
from copy import copy

class TrackerRecording(Recording):

    def __init__(self, robot_name, marker_namespace):
        super(TrackerRecording, self).__init__(robot_name)
        self.marker = Marker(marker_namespace)
        self.tracker = True

    def gen_wide_joint_positions(self, nsamples=6):
        q = np.zeros((6))
        for sample1 in range(nsamples):
            q[0] = np.deg2rad(-40 + (sample1) / (nsamples - 1) * 105)
            for sample2 in range(nsamples):
                if sample1 % 2 == 0:
                    q[1] = np.deg2rad(-40 + (sample2) / (nsamples - 1) * 60)
                else:
                    q[1] = np.deg2rad(20 - (sample2) / (nsamples - 1) * 60)
                for sample3 in range(nsamples):
                    if sample2 % 2 == 0:
                        q[2] = .070 + (sample3) / (nsamples - 1) * .150
                    else:
                        q[2] = .220 - (sample3) / (nsamples - 1) * .150
                    yield copy(q)

    def record_joints(self, joint_set, verbose=False):
        """Record points using tracker by controlling the joints
        of the dVRK"""
        # Get number of columns of terminal and subtract it by 2 to get
        # the toolbar width
        toolbar_width = int(os.popen('stty size', 'r').read().split()[1]) - 2
        npoints = len(joint_set)
        sys.stdout.write("[%s]\r" % (" " * toolbar_width))
        sys.stdout.flush()
        start_time = time.time()
        bad_rots = 0

        for i, q in enumerate(joint_set):
            q[3:6] = self.arm.get_desired_joint_position()[3:6]
            self.arm.move_joint(q)
            self.arm.move(self.ROT_MATRIX)
            time.sleep(0.5)
            rot_matrix = self.arm.get_current_position().M
            marker_pos = self.marker.get_current_position()
            # check difference in angle
            rot_diff = self.ROT_MATRIX * rot_matrix.Inverse()
            # if difference in angle is > 2 degrees
            if np.rad2deg(rot_diff.GetRotAngle()[0]) > 2:
                rospy.logwarn("Disregarding bad orientation:\n{}"
                              .format(rot_matrix))
                bad_rots += 1
            elif marker_pos is None:
                rospy.logwarn("Disregarding bad data received from Tracker")
            else:
                # Add current position (from tracker and arm) to data
                arm_coord = self.arm.get_current_position().p
                data_dict = {
                    "arm_position_x": arm_coord[0],
                    "arm_position_y": arm_coord[1],
                    "arm_position_z": arm_coord[2],
                    "tracker_position_x": marker_pos[0],
                    "tracker_position_y": marker_pos[1],
                    "tracker_position_z": marker_pos[2],
                }
                joints = self.arm.get_current_joint_position()
                for joint_num, joint_pos in enumerate(joints):
                    data_dict.update({
                        "joint_{}_position".format(joint_num): joint_pos
                    })
                self.data.append(data_dict)
            block = int(toolbar_width * i/(npoints - 1))
            arrows = '-' * block if block < 1 else (('-' * block)[:-1] + '>')
            sys.stdout.write("\r[{}{}]".format(arrows,
                                               ' ' * (toolbar_width - block)))
            sys.stdout.flush()

        end_time = time.time()
        duration = end_time - start_time
        duration_min = int(duration) // 60
        duration_sec = int(duration % 60)
        print("Finished in {}m {}s".format(duration_min, duration_sec))
        print(rospy.get_caller_id(), '<- recording complete')
        print("Number of bad points: {}"
              .format(self.marker.n_bad_callbacks + bad_rots))

    def output_to_csv(self):
        """Outputs contents of self.data to fpath"""
        filename = "tracker_point_cloud.csv"

        with open(os.path.join(self.folder, filename), 'w') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=self.data[0].keys())
            writer.writeheader()
            writer.writerows(self.data)
