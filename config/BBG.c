#include <linux/fs.h>
#include <linux/dcache.h>
#include <linux/string.h>
#include <linux/printk.h>
#include <linux/blkdev.h>
#include <linux/panic.h>

/* Список защищаемых разделов и критических сигнатур */
static const char *protected_targets[] = {
    "boot", "bootloader", "radio", "modem", "nvram", "nvdata",
    "persist", "metadata", "connsys", "protect", "seccfg",
    "preloader", "logo", "efuse", "xloader", "sdc"
};

/* Основная функция проверки для FS-хуков (например, vfs_rmdir) */
void bbg_check(void *mnt, struct dentry *dentry, int type) {
    if (!dentry || !dentry->d_name.name)
        return;

    const char *name = dentry->d_name.name;
    int i;
    int size = sizeof(protected_targets) / sizeof(protected_targets[0]);

    for (i = 0; i < size; i++) {
        if (strstr(name, protected_targets[i])) {
            pr_emerg("[BBG] СЕКЬЮРИТИ: Заблокирована вредоносная операция (%d) на разделе: %s\n", type, name);
            /* Вызываем панику ядра для предотвращения уничтожения данных */
            panic("[BBG] Попытка повреждения критического раздела! Система остановлена во избежание кирпича.\n");
        }
    }
}

/* Дополнительный хук для блокировки прямой записи (dd) на уровне блочного устройства */
int bbg_block_write_check(struct block_device *bdev, fmode_t mode) {
    if (!bdev || !bdev->bd_disk)
        return 0;

    const char *disk_name = bdev->bd_disk->disk_name;
    int i;
    int size = sizeof(protected_targets) / sizeof(protected_targets[0]);

    /* Проверяем режим записи */
    if (mode & FMODE_WRITE) {
        for (i = 0; i < size; i++) {
            if (strstr(disk_name, protected_targets[i])) {
                pr_emerg("[BBG] ПРЕДУПРЕЖДЕНИЕ: Перехвачена попытка dd/записи в %s!\n", disk_name);
                /* Возвращаем ошибку доступа (Operation not permitted) */
                return -EPERM; 
            }
        }
    }
    return 0;
}