import subprocess
import re
import time
import math

import pygame
from pygame.locals import *

from OpenGL.GL import *
from OpenGL.GLU import *


# =====================================
# AXIS ASSIGNMENT
# =====================================

GYRO_X = (17,18)
GYRO_Y = (19,20)
GYRO_Z = (21,22)

ACCEL_X = (23,24)
ACCEL_Y = (25,26)
ACCEL_Z = (27,28)



# =====================================
# HID PARSER
# =====================================

def parse_report(line):

    if not line.startswith(" "):
        return None

    data = re.findall(r"[0-9A-Fa-f]{2}", line)

    if len(data) < 29:
        return None

    return [int(x,16) for x in data]



def read_s16(report, lo, hi):

    value = report[lo] | (report[hi] << 8)

    if value >= 32768:
        value -= 65536

    return value



# =====================================
# CUBE
# =====================================

vertices = (
    (-1,-1,-1),
    ( 1,-1,-1),
    ( 1, 1,-1),
    (-1, 1,-1),

    (-1,-1,1),
    ( 1,-1,1),
    ( 1, 1,1),
    (-1, 1,1),
)


edges = (
    (0,1),(1,2),(2,3),(3,0),
    (4,5),(5,6),(6,7),(7,4),
    (0,4),(1,5),(2,6),(3,7)
)


def draw_cube():

    glBegin(GL_LINES)

    for edge in edges:
        for vertex in edge:
            glVertex3fv(vertices[vertex])

    glEnd()



# =====================================
# MAIN
# =====================================

def main():

    print()
    print("Vader 5 Pro gyro + accel cube")
    print("-----------------------------")
    print("Keep controller still for calibration")
    print()


    cmd = [
        ".\\hidapitester.exe",
        "--vidpid",
        "37D7:2401",
        "--usagePage",
        "0xFFA0",
        "--open",
        "--length",
        "32",
        "--read-input-forever"
    ]


    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )


    pygame.init()

    display=(800,600)

    pygame.display.set_mode(
        display,
        DOUBLEBUF | OPENGL
    )

    gluPerspective(
        45,
        display[0]/display[1],
        0.1,
        50
    )

    glTranslatef(0,0,-6)



    # -----------------------------
    # Calibration
    # -----------------------------

    bias_x=0
    bias_y=0
    bias_z=0

    samples=0

    start=time.time()

    print("Calibrating...")


    while time.time()-start < 2:

        line=process.stdout.readline()

        report=parse_report(line)

        if report:

            bias_x += read_s16(report,*GYRO_X)
            bias_y += read_s16(report,*GYRO_Y)
            bias_z += read_s16(report,*GYRO_Z)

            samples+=1


    if samples:

        bias_x/=samples
        bias_y/=samples
        bias_z/=samples


    print("Bias:")
    print(
        round(bias_x,2),
        round(bias_y,2),
        round(bias_z,2)
    )

    print("Starting cube")


    # orientation

    roll=0
    pitch=0
    yaw=0


    last=time.time()


    # tuning

    gyro_scale=0.015

    accel_strength=0.04



    for line in process.stdout:


        report=parse_report(line)

        if not report:
            continue



        gx=read_s16(report,*GYRO_X)-bias_x
        gy=read_s16(report,*GYRO_Y)-bias_y
        gz=read_s16(report,*GYRO_Z)-bias_z


        ax=read_s16(report,*ACCEL_X)
        ay=read_s16(report,*ACCEL_Y)
        az=read_s16(report,*ACCEL_Z)



        now=time.time()

        dt=now-last
        last=now



        # gyro integration

        roll  += gx * dt * gyro_scale
        pitch += gy * dt * gyro_scale
        yaw   += gz * dt * gyro_scale



        # -----------------------------
        # Accelerometer gravity vector
        # -----------------------------

        length=math.sqrt(
            ax*ax+
            ay*ay+
            az*az
        )


        if length > 100:

            ax/=length
            ay/=length
            az/=length


            accel_roll = math.degrees(
                math.atan2(
                    ay,
                    az
                )
            )


            accel_pitch = math.degrees(
                math.atan2(
                    -ax,
                    math.sqrt(
                        ay*ay+
                        az*az
                    )
                )
            )


            # complementary correction

            roll = (
                roll*(1-accel_strength)
                +
                accel_roll*accel_strength
            )


            pitch = (
                pitch*(1-accel_strength)
                +
                accel_pitch*accel_strength
            )



        for event in pygame.event.get():

            if event.type == pygame.QUIT:
                raise KeyboardInterrupt



        glClear(
            GL_COLOR_BUFFER_BIT |
            GL_DEPTH_BUFFER_BIT
        )


        glPushMatrix()


        glRotatef(
            roll,
            1,0,0
        )

        glRotatef(
            pitch,
            0,1,0
        )

        glRotatef(
            yaw,
            0,0,1
        )


        draw_cube()


        glPopMatrix()


        pygame.display.flip()



if __name__=="__main__":

    try:
        main()

    except KeyboardInterrupt:

        print("Stopped")