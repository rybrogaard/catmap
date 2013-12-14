#!/usr/bin/env python
from subprocess import Popen, PIPE
import os

output = Popen(['git', 'rev-list', 'HEAD','--count'],stdout=PIPE)
rev = output.stdout.read().strip()
init = open('catmap/__init__.py')
init_txt = init.read()
init.close()
new_txt = []
for li in init_txt.split('\n'):
    if '__version__' in li:
        oldversion = li.rsplit('.',1)[0]
        newversion = oldversion + '.' + rev + '"'
        new_txt.append(newversion)
    else:
        new_txt.append(li)

new_init = '\n'.join(new_txt)
init = open('catmap/__init__.py','w')
init.write(new_init)
init.close()

message = raw_input('Submit message:')
os.system('git commit -am "'+message+'"')
os.system('git push')
