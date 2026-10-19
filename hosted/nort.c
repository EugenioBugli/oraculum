// Preloaded into the robot processes of a hosted session (robot.sh): the Modal sandbox (gVisor) allows no real-time
// scheduling and no memory locking, which the robot containers get from Docker (SYS_NICE, rtprio 99, memlock).
// booster-motion's control thread fails without them; in a simulation, normal scheduling is enough.
#include <pthread.h>
#include <sched.h>
#include <sys/mman.h>

int pthread_setschedparam(pthread_t thread, int policy, const struct sched_param *param) { return 0; }
int sched_setscheduler(pid_t pid, int policy, const struct sched_param *param) { return 0; }
int sched_setparam(pid_t pid, const struct sched_param *param) { return 0; }
int mlockall(int flags) { return 0; }
