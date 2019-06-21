import csv
import numpy as np
import scipy.linalg
import cisstRobotPython as crp

ROB_FILE = ("/home/cnookal1/catkin_ws/src/cisst-saw"
            "/sawIntuitiveResearchKit/share/deprecated/dvpsm.rob")

def get_best_fit(pts):
    # best-fit linear plane
    A = np.c_[pts[:, 0], pts[:, 1], np.ones(pts.shape[0])]
    C, _, _, _ = scipy.linalg.lstsq(A, pts[:, 2])    # coefficients
    return C


def get_best_fit_error(pts):
    A, B, C = get_best_fit(pts)
    errors = np.array([])

    direction = np.array([A, B, -1])
    normal = direction / np.linalg.norm(direction)

    projections = np.array([])

    for pt in pts:
        dist = np.dot(normal, pt - np.array([0, 0, C]))
        projection = pt - dist * normal
        projections = np.append(projections, projection)
        projections = projections.reshape(-1, 3)
        errors = np.append(errors, dist)
        # If this value is close to 0, then the distances are accurate
        # print(A * projection[0] + B * projection[1] + C - projection[2])

    return np.sqrt(sum([error ** 2 for error in errors]) /
                                len(errors))


def get_new_offset(data_file=None, error_fk_outfile=None):

    rob = crp.robManipulator()
    rob.LoadRobot(ROB_FILE)

    min = 0
    min_offset = 0

    joints = np.array([])
    coords = np.array([])

    with open(data_file) as infile:
        reader = csv.reader(infile)
        for row in reader:
            joints = np.append(joints,
                               np.array([float(x) for x in row[3:9]]))
            coords = np.append(coords,
                               np.array([float(x) for x in row[:3]]))

    coords = coords.reshape(-1, 3)
    joints = joints.reshape(-1, 6)

    # Add checker for outfile
    with open(error_fk_outfile, 'w') as outfile:
        fk_plot = csv.writer(outfile)
        for num, offset in enumerate(np.arange(-.9, .09, .001)):
            data = joints.copy()
            fk_pts = np.array([])
            for q in data:
                q[2] += offset
                fk_pts = np.append(fk_pts, rob.ForwardKinematics(q)[:3, 3])
            fk_pts = fk_pts.reshape((-1, 3))
            error = get_best_fit_error(fk_pts)
            if num == 0 or error < min:
                min = error
                min_offset = offset
            fk_plot.writerow([offset, error])

    for num, offset in enumerate(np.arange(min_offset - 0.02,
                                           min_offset + 0.02,
                                           0.0001)):
        data = joints.copy()
        fk_pts = np.zeros(coords.shape)
        for i, q in enumerate(data):
            q[2] += offset
            fk_pts[i] = rob.ForwardKinematics(q)[:3, 3]
        error = get_best_fit_error(fk_pts)
        if num == 0 or error < min:
            min = error
            min_offset = offset

    return min_offset
