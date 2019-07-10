#!/usr/bin/env python

from __future__ import print_function, division
import sys
import os.path
from copy import copy
import time
from datetime import datetime
import argparse
import xml.etree.ElementTree as ET
import csv
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import PyKDL
import rospy
import dvrk
from analyze_data import get_new_offset, get_best_fit, get_new_offset_polaris
from marker import Marker
from cisstNumericalPython import nmrRegistrationRigid

class Calibration:

    ROT_MATRIX = PyKDL.Rotation(
        1,    0,    0,
        0,   -1,    0,
        0,    0,   -1
    )

    THRESH = 1.5

    def __init__(self, robot_name, polaris=False):
        print("initializing calibration for", robot_name)
        print("have a flat surface below the robot")
        self.data = []
        self.info = {}
        # Add checker for directory
        strdate = time.strftime("%Y-%m-%d_%H-%M-%S")
        self.folder = os.path.join("data", "{}_{}".format(robot_name, strdate))
        os.mkdir(self.folder)
        print("Created folder at {}".format(os.path.abspath(self.folder)))

        self.arm = dvrk.psm(robot_name)
        self.home()
        if polaris:
            self.marker = Marker()
            self.polaris = True
        else:
            self.polaris = False

    def home(self):
        "Goes to x = 0, y = 0, extends joint 2 past the cannula, and sets home"
        # make sure the camera is past the cannula and tool vertical
        print("starting home")
        self.arm.home()
        self.arm.close_jaw()
        goal = np.zeros(6)
        if ((self.arm.name() == 'PSM1') or (self.arm.name() == 'PSM2') or
            (self.arm.name() == 'PSM3') or (self.arm.name() == 'ECM')):
            # set in position joint mode
            goal[2] = 0.12
            self.arm.move_joint(goal)
        self.arm.move(self.ROT_MATRIX)

    def get_corners(self):
        "Gets input from user to get three corners of the plane"
        pts = []
        raw_input("Pick the first corner, then press enter. ")
        pts.append(self.arm.get_current_position())
        raw_input("Pick the second corner, then press enter. ")
        pts.append(self.arm.get_current_position())
        raw_input("Pick the third corner, then press enter. ")
        pts.append(self.arm.get_current_position())
        return pts

    def palpate(self, output_file, show_graph=True):
        """Move down until forces act on the motor in the z direction,
        then record position, joints, and wrench body of the robot"""

        time.sleep(2)
        goal = self.arm.get_desired_position()

        # Store z-position and force in pos_v_force
        pos_v_force = []
        MM = 0.001
        TENTH_MM = 0.0001

        # Calculate number of steps required to move 2 cm with an increment of 1 mm
        STEPS_MM = int(0.02/MM)

        # Calculate number of steps required to move 4 mm with an increment of 0.1 mm
        STEPS_TENTH_MM = int(0.004/TENTH_MM)

        oldtime = time.time()

        goal.p[2] += 0.01

        for i in range(STEPS_MM):
            goal.p[2] -= MM
            self.arm.move(goal)
            time.sleep(0.1)
            if self.arm.get_current_wrench_body()[2] > self.THRESH:
                # Record initial contact
                goal.p = self.arm.get_current_position().p
                break
            elif i == STEPS_MM - 1:
                return False

        print(time.time() - oldtime)

        import pudb; pudb.set_trace()  # XXX BREAKPOINT
        # move arm 2mm up
        goal.p[2] += 0.002

        time.sleep(2)


        oldtime = time.time()

        for i in range(STEPS_TENTH_MM): # in tenths of millimeters
            goal.p[2] -= TENTH_MM
            self.arm.move(goal)
            time.sleep(0.5)
            force = self.arm.get_current_wrench_body()[2]
            z_pos = self.arm.get_current_position().p[2]
            pos_v_force.append([z_pos, force])
            if abs(force) >= self.THRESH + .5:
                goal.p[2] += 0.05
                break
            elif i == STEPS_TENTH_MM - 1:
                return False

        print(time.time() - oldtime)

        data_moving = []
        data_contact = []

        # Sort pos_v_force based on z-position
        pos_v_force = np.array(sorted(pos_v_force, key=lambda t:t[0]))

        moving = False
        for i, pt in enumerate(pos_v_force[1:]):
            # pos_v_force[i] is pos_v_force[1:][i-1], not the same as pt
            deriv = derivative(pt, pos_v_force[i])
            if deriv < -300:
                if moving:
                    break
                else:
                    data_contact.append(pos_v_force[i])
            else:
                moving = True
                data_moving.append(pos_v_force[i])


        data_moving = np.array(data_moving)
        data_contact = np.array(data_contact)

        eqn = np.polyfit(data_contact[:, 0], data_contact[:, 1], 1)
        k = sum(data_moving[:,1])/len(data_moving)
        new_z = (eqn[1] - k)/(-eqn[0])

        print("Using {} instead of {}".format(new_z, goal.p[2] - 0.05))

        if show_graph:
            x = np.sort(np.append(data_moving[:,0], data_contact[:,0]))
            plt.plot(x, eqn[0] * x + eqn[1], '-')
            # Plot horizontal line
            plt.axhline(y=k, color='r', linestyle='-')

            # First plot all points, then plot the contact points and moving points
            plt.scatter(pos_v_force[:,0], pos_v_force[:,1], s=10, color='green')
            plt.scatter(data_moving[:,0], data_moving[:,1], s=10, color='red')
            plt.scatter(data_contact[:,0], data_contact[:,1], s=10, color='blue')
            plt.show()

        outfile = open(output_file, 'w')
        writer = csv.writer(outfile)
        writer.writerows(pos_v_force)

        return True


    def record_points(self, pts, nsamples, verbose=False):
        """Moves in a zig-zag pattern in a grid and records the points
        at which the arm reaches the surface"""
        if not len(pts) == 3:
            return False

        self.info["points"] = [pt.p for pt in pts]
        self.info["polaris"] = False


        final = PyKDL.Frame()
        final.p = copy(pts[0].p)
        final.M = self.ROT_MATRIX
        final.p[2] += 0.15

        self.arm.move(final)
        final.p[2] -= 0.1
        self.arm.move(final)

        goal = PyKDL.Frame(self.ROT_MATRIX)
        print("Using points {}, {}, and {}".format(*[tuple(pt.p) for pt in pts]))

        for i in range(nsamples):
            rightside = pts[1].p + i / (nsamples - 1) * (pts[2].p - pts[1].p)
            leftside = pts[0].p + i / (nsamples - 1) * (pts[2].p - pts[1].p)
            print("moving arm to row ", i)
            for j in range(nsamples):
                print("\tmoving arm to column ", j)
                goal = PyKDL.Frame(self.ROT_MATRIX)
                if i % 2 == 0:
                    goal.p = leftside + (j / (nsamples - 1) *
                                         (rightside - leftside))
                else:
                    goal.p = rightside + (j / (nsamples - 1) *
                                          (leftside - rightside))
                goal.p[2] += 0.01
                self.arm.move(goal)

                palpate_file = os.path.join(
                    self.folder,
                    "palpation_{}_{}.csv".format(i, j)
                )

                if not self.palpate(palpate_file):
                    rospy.logerr("Didn't reach surface. Closing program")
                    sys.exit(1)

                time.sleep(0.5)

        print(rospy.get_caller_id(), '<- calibration complete')

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
                    yield q

    def record_joints_polaris(self, joint_set, npoints=216, verbose=False):
        """Record points using polaris by controlling the joints
        of the dVRK"""
        # Get number of columns of terminal and subtract it by 2 to get
        # the toolbar width
        toolbar_width = int(os.popen('stty size', 'r').read().split()[1]) - 2
        sys.stdout.write("[%s]\r" % (" " * toolbar_width))
        sys.stdout.flush()
        start_time = time.time()
        bad_rots = 0

        for i, q in enumerate(joint_set):
            q[3:6] = self.arm.get_desired_joint_position()[3:6]
            self.arm.move_joint(q)
            self.arm.move(self.ROT_MATRIX)
            time.sleep(0.5)
            marker_pos = self.marker.get_current_position()
            rot_matrix = self.arm.get_current_position().M
            rot_diff = self.ROT_MATRIX * rot_matrix.Inverse()
            if np.rad2deg(np.abs(rot_diff.GetRPY()).max()) > 2:
                rospy.logwarn("Disregarding bad orientation:\n{}".format(rot_matrix))
                bad_rots += 1
            elif marker_pos is None:
                rospy.logwarn("Disregarding bad data received from Polaris")
            else:
                self.data.append(
                    list(self.arm.get_current_joint_position()) +
                    list(self.arm.get_current_position().p) +
                    list(marker_pos)
                )
            block = int(toolbar_width * i/(npoints - 1))
            arrows = '-' * block if block < 1 else (('-' * block)[:-1] + '>')
            sys.stdout.write("\r[{}{}]".format(arrows, ' ' * (toolbar_width - block)))
            sys.stdout.flush()

        end_time = time.time()
        duration = end_time - start_time
        print("Finished in {}m {}s".format(int(duration) // 60, int(duration % 60)))
        print(rospy.get_caller_id(), '<- calibration complete')
        print("Number of bad points: {}".format(self.marker.n_bad_callbacks + bad_rots))

    def gen_grid(self, corners, nsamples, verbose=False):
        """Moves in a zig-zag pattern in a grid and records the points
        at which the arm reaches the surface"""
        if not len(corners) == 3:
            return

        self.info["corners"] = [corner.p for corner in corners]
        self.info["polaris"] = True

        goal = PyKDL.Frame(self.ROT_MATRIX)

        if verbose:
            print("Using corners {}, {}, and {}".format(*[tuple(pt.p) for pt in corners]))

        for i in range(nsamples):
            rightside = corners[1].p + i / (nsamples - 1) * (corners[2].p - corners[1].p)
            leftside = corners[0].p + i / (nsamples - 1) * (corners[2].p - corners[1].p)
            if verbose:
                print("moving arm to row ", i)
            for j in range(nsamples):
                if verbose:
                    print("\tmoving arm to column ", j)
                if i % 2 == 0:
                    goal.p = leftside + (j / (nsamples - 1) *
                                         (rightside - leftside))
                else:
                    goal.p = rightside + (j / (nsamples - 1) *
                                          (leftside - rightside))
                goal.M = self.ROT_MATRIX
                yield goal

    def record_points_polaris(self, pts, npoints=100, verbose=False):
        # Get number of columns of terminal and subtract it by 2 to get
        # the toolbar width
        toolbar_width = int(os.popen('stty size', 'r').read().split()[1]) - 2
        sys.stdout.write("[%s]\r" % (" " * toolbar_width))
        sys.stdout.flush()

        for i, pt in enumerate(pts):
            self.arm.move(pt)
            time.sleep(0.5)
            m = list(self.marker.get_current_position())
            self.data.append(
                list(self.arm.get_current_joint_position()) +
                list(self.arm.get_current_position().p) +
                m
            )
            block = int(toolbar_width * i/(npoints - 1))
            arrows = '-' * block if block < 1 else (('-' * block)[:-1] + '>')
            sys.stdout.write("\r[{}{}]".format(arrows, ' ' * (toolbar_width - block)))
            sys.stdout.flush()

        print(rospy.get_caller_id(), '<- calibration complete')
        print("Number of bad points: {}".format(self.marker.n_bad_callbacks))

    def output_to_csv(self, fpath):
        "Outputs contents of self.data to fpath"
        with open(choose_filename(fpath), 'w') as csvfile:
            info_text = " ,".join([
                "{}: {}".format(key, value)
                for (key, value) in self.info.iteritems()
            ])

            csvfile.write("# INFO: {}\n".format(info_text))
            writer = csv.writer(
                csvfile, delimiter=',',
                quotechar='"', quoting=csv.QUOTE_MINIMAL
            )
            for row in self.data:
                writer.writerow(row)


def choose_filename(fpath):
    """checks if file at fpath already exists.
    If so, it increments the file"""
    if not os.path.exists(fpath):
        new_fname = fpath
    else:
        fname, file_ext = os.path.splitext(fpath)
        i = 1
        new_fname = "{}_{}{}".format(fname, i, file_ext)
        while os.path.exists(new_fname):
            i += 1
            new_fname = "{}_{}{}".format(fname, i, file_ext)
    return new_fname


def plot_data(data_file):
    "Plots the data from the csv file data_file"
    coords = np.array([])

    polaris_coords = np.array([])

    joints = np.array([])

    with open(data_file, 'r') as csvfile:
        csvfile.readline()
        reader = csv.reader(csvfile)
        for row in reader:
            if len(row) == 12:
                polaris = True
            else:
                polaris = False
            joints = np.append(
                joints,
                np.array([float(x) for x in row[0:6]])
            )
            coords = np.append(
                coords,
                np.array([float(x) for x in row[6:9]])
            )
            if polaris:
                polaris_coords = np.append(
                    polaris_coords,
                    np.array([float(x) for x in row[9:12]])
                )
    coords = coords.reshape(-1, 3)

    if polaris:
        polaris_coords = polaris_coords.reshape(-1, 3)

    joints = joints.reshape(-1, 6)


    if polaris:
        transf, error = nmrRegistrationRigid(coords, polaris_coords)
        rot_matrix = transf.Rotation()
        translation = transf.Translation()
        polaris_coords = (polaris_coords - translation).dot(rot_matrix)
        print("Rigid Registration Error: {}".format(error))

    if not polaris:
        X, Y = np.meshgrid(
            np.arange(
                min(coords[:,0])-0.05,
                max(coords[:,0])+0.05,
                0.05
            ),
            np.arange(
                min(coords[:,1])-0.05,
                max(coords[:,1])+0.05,
                0.05
            )
        )

        A, B, C = get_best_fit(coords)
        Z = A*X + B*Y + C

    # plot points and fitted surface
    fig = plt.figure()
    ax = fig.gca(projection='3d')
    if polaris:
        ax.scatter(polaris_coords[:,0], polaris_coords[:,1], polaris_coords[:,2],
            c='b', s=20)
    else:
        ax.plot_surface(X, Y, Z, rstride=1, cstride=1, alpha=0.2)
    ax.scatter(coords[:,0], coords[:,1], coords[:,2], c='r', s=20)
    plt.xlabel('X')
    plt.ylabel('Y')
    ax.set_zlabel('Z')
    plt.show()


def parse_record(args):
    pts = [
        PyKDL.Vector(0.04969137179347108, 0.12200283317260341, -0.19149147092692725),
        PyKDL.Vector(0.09269885200354012, -0.06284151552138104, -0.1977706048728867),
        PyKDL.Vector(-0.06045055029036737, -0.11093816039641696, -0.19326454699986603)
    ]
    pts = [PyKDL.Frame(Calibration.ROT_MATRIX, pt) for pt in pts]
    if args.polaris:
        calibration = Calibration(args.arm, polaris=True, output=True)
        # pts = calibration.get_corners()
        # grid = calibration.gen_grid(pts, args.samples, verbose=args.verbose)
        # calibration.record_points_polaris(grid, verbose=args.verbose)
        joint_set = calibration.gen_wide_joint_positions()
        print("Starting calibration")
        time.sleep(0.5)
        calibration.record_joints_polaris(joint_set, npoints=216, verbose=args.verbose)
    else:
        calibration = Calibration(args.arm)
        # pts = calibration.get_corners()
        goal = pts[0]
        goal.p[2] += 0.100
        calibration.arm.move(goal)
        goal.p[2] -= 0.090
        calibration.arm.move(goal)
        calibration.palpate(os.path.join(calibration.folder, "single_palpation.csv"))

        # calibration.record_points(pts, args.samples, verbose=args.verbose)

    # calibration.output_to_csv(args.output)


def parse_view(args):
    plot_data(args.input)


def parse_analyze(args):
    if args.polaris:
        offset = 1000 * get_new_offset_polaris(args.input, args.output)
    else:
        offset = 1000 * get_new_offset(args.input, args.output)
    if args.write:
        if os.path.exists(args.write):
            print("Writing offset...")
            tree = ET.parse(args.write)
            root = tree.getroot()
            xpath_search_results = root.findall("./Robot/Actuator[@ActuatorID='2']/AnalogIn/VoltsToPosSI")
            if len(xpath_search_results) == 1:
                VoltsToPosSI = xpath_search_results[0]
            else:
                print("Error: There must be exactly one Actuator with ActuatorID=2")
                sys.exit(1)
            current_offset = float(VoltsToPosSI.get("Offset"))
            VoltsToPosSI.set("Offset", str(offset + current_offset))
            tree.write(args.write)
            print(("Wrote offset: {}mm (Current offset) + {}mm (Additional offset) "
                   "= {}mm (Written offset)").format(current_offset, offset,
                                                   offset + current_offset))
        else:
            print("Error: File does not exist")
            sys.exit(1)
    else:
        print("Offset: {}mm".format(offset))

def derivative(p1, p2):
    return (p2[1] - p1[1]) / (p2[0] - p1[0])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calibrate the dVRK")
    parser.add_argument(
        "-v", "--verbose",
        help="make output verbose", action="store_true"
    )

    subparser = parser.add_subparsers(title="subcommands")

    parser_record = subparser.add_parser(
        "record",
        help="record data for calibration"
    )
    parser_record.add_argument(
        "arm",
        help="arm to record points from"
    )
    parser_record.add_argument(
        "-o", "--output",
        help="folder to output data",
    )
    parser_record.add_argument(
        "-p", "--polaris",
        help="use polaris",
        default=False,
        action="store_true"
    )
    parser_record.add_argument(
        "-n", "--samples",
        help="number of samples per row "
        "(10 is recommended to get higher quality data)",
        default=10,
        type=int,
    )
    parser_record.set_defaults(func=parse_record)

    parser_view = subparser.add_parser("view", help="view outputted data")
    parser_view.add_argument(
        "input", help="data to read from",
        nargs='?', default="data/data.csv"
    )
    parser_view.set_defaults(func=parse_view)

    parser_analyze = subparser.add_parser(
        "analyze",
        help="analyze outputted data and find offset"
    )
    parser_analyze.add_argument(
        "input",
        help="data to read from",
        nargs='?',
        default="data/data.csv"
    )
    parser_analyze.add_argument(
        "-o", "--output",
        help="output for the graph of offset versus error "
        "(filename automatically increments)",
        default="data/error_fk.csv"
    )
    parser_analyze.add_argument(
        "-p", "--polaris",
        help="use polaris",
        default=False,
        action="store_true"
    )
    parser_analyze.add_argument(
        "-n", "--no-output",
        help="do not output graph of offset versus error",
        default=False,
        action="store_true"
    )
    parser_analyze.add_argument(
        "-w", "--write",
        help="write offset to file",
        default=False,
    )
    parser_analyze.set_defaults(func=parse_analyze)

    args = parser.parse_args()
    args.func(args)

