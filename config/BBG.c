#include <linux/fs.h>
#include <linux/dcache.h>
#include <linux/string.h>
#include <linux/printk.h>
#include <linux/blkdev.h>
#include <linux/errno.h>
#include <linux/sched.h>

static const char *protected_targets[] = {
    "boot",
    "vendor_boot",
    "init_boot",
    "dtbo",
    "vbmeta",
    "vbmeta_system",
    "vbmeta_vendor",
    "super",
    "metadata",
    "persist",
    "modem",
    "nvram",
    "nvdata",
    "protect",
    "protect1",
    "protect2",
    "seccfg",
    "preloader",
    "lk",
    "logo",
    "efuse",
    "xloader",
    "tee",
    "connsys"
};

static bool bbg_is_whitelisted(void)
{
    const char *comm = current->comm;

    if (!strcmp(comm, "init"))
        return true;

    if (!strcmp(comm, "ueventd"))
        return true;

    if (!strcmp(comm, "update_engine"))
        return true;

    if (!strcmp(comm, "fastbootd"))
        return true;

    if (!strcmp(comm, "recovery"))
        return true;

    if (current->flags & PF_KTHREAD)
        return true;

    return false;
}

static bool bbg_match(const char *name)
{
    int i;

    if (!name)
        return false;

    for (i = 0; i < ARRAY_SIZE(protected_targets); i++) {
        if (strstr(name, protected_targets[i]))
            return true;
    }

    return false;
}

int bbg_fs_check(struct dentry *dentry, int op)
{
    const char *name;

    if (!dentry)
        return 0;

    if (bbg_is_whitelisted())
        return 0;

    name = dentry->d_name.name;

    if (!name)
        return 0;

    if (bbg_match(name)) {
        pr_emerg("[BBG] blocked fs operation=%d target=%s pid=%d comm=%s\n",
                 op,
                 name,
                 current->pid,
                 current->comm);

        return -EPERM;
    }

    return 0;
}

int bbg_block_write_check(struct block_device *bdev, fmode_t mode)
{
    const char *disk_name;

    if (!bdev)
        return 0;

    if (!bdev->bd_disk)
        return 0;

    if (bbg_is_whitelisted())
        return 0;

    if (!(mode & FMODE_WRITE))
        return 0;

    disk_name = bdev->bd_disk->disk_name;

    if (!disk_name)
        return 0;

    if (bbg_match(disk_name)) {
        pr_emerg("[BBG] blocked block write target=%s pid=%d comm=%s\n",
                 disk_name,
                 current->pid,
                 current->comm);

        return -EPERM;
    }

    return 0;
}
