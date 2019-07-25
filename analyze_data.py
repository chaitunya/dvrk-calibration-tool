from __future__ import division, print_function
import csv
import os.path
import numpy as np
import scipy.linalg
import cisstRobotPython as crp
from cisstNumericalPython import nmrRegistrationRigid

ROB_FILE = ("/home/cnookal1/catkin_ws/src/cisst-saw"
            "/sawIntuitiveResearchKit/share/deprecated/dvpsm.rob")


def get_best_fit_plane(pts):
    """
    Gets the plane of best fit for `pts` along with the error
    :param np.ndarray pts The points to fit the plane to
    :returns the coefficients of the plane along with the error in the format (coefficients, error)
    :rtype tuple(tuple(float, float, float), float)
    """
    A = np.c_[pts[:, 0], pts[:, 1], np.ones(pts.shape[0])]
    (a, b, c), _, _, _ = scipy.linalg.lstsq(A, pts[:, 2])    # coefficients

    errors = np.array([])

    direction = np.array([a, b, -1])
    normal = direction / np.linalg.norm(direction)

    projections = np.array([])

    for pt in pts:
        dist = np.dot(normal, pt - np.array([0, 0, c]))
        projection = pt - dist * normal
        projections = np.append(projections, projection)
        projections = projections.reshape(-1, 3)
        errors = np.append(errors, dist)
        # If this value is close to 0, then the distances are accurate
        # print(A * projection[0] + B * projection[1] + c - projection[2])

    return (a, b, c), np.sqrt(sum([error ** 2 for error in errors]) /
                                len(errors))

def get_poly_min(pts, deg=2):
    """
    Fits a quadratic equation to `pts` and gets quadratic minimum of equation
    :param numpy.ndarray pts The points to get the minimum of
    """
    polyfit = np.polynomial.Polynomial.fit(pts[:, 0], pts[:, 1], deg)
    equation = polyfit.convert().coef
    x = np.arange(pts[0, 0], pts[-1, 0] + 0.0001, 0.0001)
    y = np.zeros(x.shape)
    for exp, coef in enumerate(equation):
        y += coef * x ** exp
    min_y = np.amin(y)
    min_x = x[np.where(y == min_y)][0]

    return equation, np.array([min_x, min_y])


def get_offset_v_error(offset_v_error_filename, data_files, polaris=False):

    rob = crp.robManipulator()
    rob.LoadRobot(ROB_FILE)

    joint_set = np.array([])
    joint_sets = []
    coords = np.array([])
    coord_set = []

    if polaris:
        polaris_coords = np.array([])
        polaris_coord_set = []

    # Accepts n number of data_files

    # Loop through data_files and put joint sets into `joint_sets` variable and coord set into
    # `coord_set` variable
    for data_file in data_files:
        with open(data_file) as infile:
            # infile.readline() # Disregard comment line
            reader = csv.DictReader(infile)
            for row in reader:
                # print(row)
                joints = np.array([
                    float(row["joint_{}_position".format(joint_num)])
                    for joint_num in range(6)
                ])
                joint_set = np.append(joint_set, joints)
                coord = np.array([
                    float(row["arm_position_x"]),
                    float(row["arm_position_y"]),
                    float(row["arm_position_z"])
                ])
                coords = np.append(coords, coord)
                if polaris:
                    polaris_coord = np.array([
                        float(row["polaris_position_x"]),
                        float(row["polaris_position_y"]),
                        float(row["polaris_position_z"])
                    ])
                    polaris_coords = np.append(polaris_coords, polaris_coord)

        coords = coords.reshape(-1, 3)
        coord_set.append(coords)

        joint_set = joint_set.reshape(-1, 6)
        joint_sets.append(joint_set)

        if polaris:
            polaris_coords = polaris_coords.reshape(-1, 3)
            polaris_coord_set.append(polaris_coords)


    with open(offset_v_error_filename, 'w') as outfile:
        fk_plot = csv.DictWriter(outfile, fieldnames=["offset", "error"])
        fk_plot.writeheader()
        offset_v_error = np.array([])

        # -2cm to 2cm
        # In tenths of a millimeter
        for num, offset in enumerate(range(-200, 200, 1)):
            fk_pt_set = []
            # Go through each file's `joint_set` and `coords`
            for joint_set, coords in zip(joint_sets, coord_set):
                data = joint_set.copy()
                fk_pts = np.array([])
                for q in data:
                    # Change 2nd joint by `offset` tenths of a millimeter
                    q[2] += offset / 10000
                    # Run forward kinematics on each point and get result
                    fk_pts = np.append(fk_pts, rob.ForwardKinematics(q)[:3, 3])
                fk_pts = fk_pts.reshape((-1, 3))
                fk_pt_set.append(fk_pts)

            # Get sum of errors of all files
            if polaris:
                # Use rigid registration if polaris is used
                error = sum([
                    nmrRegistrationRigid(coords_fk, coords_polaris)[1] # Returns transf, err
                    for coords_fk, coords_polaris in zip(fk_pt_set, polaris_coord_set)
                ])
            else:
                # Use plane of best fit if palpation is used
                error = sum([
                    get_best_fit_plane(coords_fk)[1] # Returns equation, err
                    for coords_fk in fk_pt_set
                ])


            # Add new points
            offset_v_error = np.append(offset_v_error, np.array([offset, error]))

            # Write plots in tenths of millimeters
            fk_plot.writerow({"offset": offset, "error": error})


    offset_v_error = offset_v_error.reshape(-1, 2)

    # Convert from tenths of a millimeter to meters
    # offset_v_error[:, 0] /= 10000

    return offset_v_error


