#!/usr/bin/env python3

import subprocess
import requests
import re
import os
import sys
import glob
import yaml
from bs4 import BeautifulSoup
from typing import *

KOJI = "https://openkoji.iscas.ac.cn/koji"


def search(package: str, version: Optional[Pattern] = None) -> Set[str]:
    response = requests.get(f"{KOJI}/search?match=glob&type=package&terms={package}")
    if response.status_code != 200:
        raise Exception("Failed to search package")
    
    soup = BeautifulSoup(response.text, "html.parser")
    builds = soup.find_all("a", href=re.compile("buildinfo\?buildID=\d+"), string=version)
    return ["/".join([KOJI, build["href"]]) for build in builds]


def getbuild(build: str, arch: Pattern = re.compile("\.rpm$")) -> Set[str]:
    response = requests.get(build)
    if response.status_code != 200:
        raise Exception("Failed to get build")
    
    soup = BeautifulSoup(response.text, "html.parser")
    rpms = soup.find_all("a", href=arch)
    return [rpm["href"] for rpm in rpms]


if __name__ == "__main__":
    packages = yaml.safe_load(open("packages.yaml"))
    for package in packages:
        # skip if specified
        if len(sys.argv) > 1 and package["name"] not in sys.argv:
            continue
        
        # define
        name = package["name"]
        builddir = os.getcwd() + "/build"
        rootdefine = f"--define=_topdir {builddir}"

        # search
        if "url" in package:
            rpms = getbuild(package["url"])
        else:
            builds = search(name, re.compile("fc38$"))
            for build in builds:
                rpms = getbuild(build)
                if len(rpms):
                    break
        
        # pre
        if "pre" in package:
            for pre in package["pre"]:
                print(f"Running pre script")
                subprocess.run(pre, shell=True)

        # rpm file
        args = ["--nodeps", "--nocheck", "--target=riscv32"]
        # args = ["--nodeps", "--nocheck"]
        if "with" in package:
            args.extend(map(lambda x: f"--with={x}", package["with"]))
        if "without" in package:
            args.extend(map(lambda x: f"--without={x}", package["without"]))
        if "undefine" in package:
            args.extend(map(lambda x: f"--undefine={x}", package["undefine"]))
        if "define" in package:
            args.extend(map(lambda x: f"--define={x[0]} {x[1] if x[1] != None else '%nil'}", package["define"].items()))
        
        if "nobuild" in package:
            for install in package["install"]:
                for rpm in rpms:
                    if not re.search(rf"/{install}-.*\.noarch\.rpm", rpm):
                        continue
                    subprocess.run(f"curl --create-dirs --output-dir {builddir}/RPMS/noarch -OL {rpm}", shell=True)
                    break
        else:
            # download and unpack
            srpm = f"srpm/{name}.src.rpm"
            spec = f"{builddir}/SPECS/{name}.spec"
            if not os.path.exists(srpm):
                subprocess.run(f"curl -L {rpms[0]} -o {srpm}", shell=True)
            subprocess.run(["rpm", rootdefine, "-i", srpm])

            # patch
            if "patch" in package:
                for patch in package["patch"]:
                    print(f"Running patch script")
                    print(patch.replace(r"%SPEC", spec))
                    subprocess.run(patch.replace(r"%SPEC", spec), shell=True)
            print(f"Building {name} with args: {args}")
            subprocess.run(["rpmbuild", rootdefine, *args, "-ba", spec])

        # install and post
        if "install" in package:
            for install in package["install"]:
                files = sorted(glob.glob(f"{builddir}/RPMS/riscv32/{install}*"))
                files += sorted(glob.glob(f"{builddir}/RPMS/noarch/{install}*"))
                if len(files) == 0:
                    continue
                print(f"Installing {install}")
                subprocess.run(f"rpm --ignorearch --nodeps -ivh {files[0]}", shell=True)
        if "post" in package:
            for post in package["post"]:
                print(f"Running post script")
                subprocess.run(post, shell=True)
