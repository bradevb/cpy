import os
import subprocess
import sys

from osxmetadata import OSXMetaData

SPACE = ' ' * 10  # Used in place of printing two tabs


def cp(src, dst):
    """Copies src to dst. Uses flags -Rpn to preserve resource forks."""
    res = subprocess.run(['/bin/cp', '-Rpn', src, f'{os.path.dirname(dst)}'], check=True)
    return res


def cp_ls(src_ls, dst_ls):
    """
    Copies contents of src_ls to dst_ls.
    Src_ls and dst_ls are expected to be the same length and in the same order.
    This yields so that progress can be printed. If an exception is encountered during the copy,
    it is added to a list of exceptions.
    The exception list is formatted like this: [[src, dst, exception], [src2, dst2, exception2], etc...]
    """
    errs = []
    for idx, (src, dst) in enumerate(zip(src_ls, dst_ls), start=1):
        try:
            if os.path.exists(dst):
                yield idx, errs
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            cp(src, dst)
            yield idx, errs
        except Exception as e:
            errs.append([src, dst, e])
        finally:
            yield idx, errs


def ls_dir(dir_path):
    """Returns a list of all directories, and files in a directory (recursively)."""
    dirs_result = []
    files_result = []

    # Append paths to all files and dirs to results
    for root, dirs, files in os.walk(dir_path):
        dirs_result.extend([os.path.join(root, current_dirs) for current_dirs in dirs])
        files_result.extend([os.path.join(root, current_files) for current_files in files])

    return dirs_result, files_result


def change_parent(old, new, paths):
    """
    Changes paths' parent from old to new. If paths is a list, will change all paths in
    that list to the new parent, and return a new list.
    """
    if isinstance(paths, str):
        return os.path.join(new, paths[len(old):])
    else:
        result = []
        for path in paths:
            stripped_path = path[len(old):]
            stripped_path = stripped_path if not stripped_path.startswith('/') else stripped_path[1:]
            result.append(os.path.join(new, stripped_path))
        return result


def clean_meta_dict(meta):
    """Takes a meta dict from osxmetadata.asdict and removes the keys starting with _."""
    result = {}
    for key, value in meta.asdict(True, True).items():
        if not key.startswith("_"):
            # skip private keys like _version and _filepath
            result[key] = value

    return result


def check_meta(src, dst):
    """Checks src's metadata against dst's."""
    src_meta = OSXMetaData(src)
    src_meta_dict = clean_meta_dict(src_meta)
    dst_meta = OSXMetaData(dst)
    dst_meta_dict = clean_meta_dict(dst_meta)

    if src_meta_dict != dst_meta_dict:
        dst_meta._restore_attributes(src_meta.asdict(all_=True, encode=True), all_=True)
        # Need to specifically set the following. They don't seem to get set with restore_attributes.
        dst_meta.finderinfo.set_finderinfo_stationarypad(src_meta.stationarypad)
        dst_meta.tags = src_meta.tags


def check_meta_ls(old, new):
    """Checks metadata of old against new. If it finds a difference, the old's metadata is copied to new."""
    ls_len = len(old)
    for idx, (src, dst) in enumerate(zip(old, new), start=1):
        check_meta(src, dst)
        print(f'Restored {idx}/{ls_len}...', end='\r')
    print()


def copy_with_progress(old, new):
    """Convenience function for copying files/dirs while displaying progress."""
    cp_errs = []
    ls_len = len(old)

    for c, errs in cp_ls(old, new):
        cp_errs = errs
        print(f'Copied {c}/{ls_len}...{SPACE}Errors: {len(cp_errs)}', end='\r', flush=True)
    print()
    return cp_errs


if __name__ == '__main__':
    # The parent folder to be copied
    SRC = '/Volumes/Archive/GRAPHIC RESOURCES'
    # The folder to copy to
    DST = '/Volumes/test/copy_files'

    print(f'Copying folder {SRC} to {DST}')
    proceed = input('Does this look correct? y/n: ').lower()
    if proceed != 'y':
        print('Exiting.')
        sys.exit(1)

    print(f'Getting list of directories and files in {SRC}...')
    old_dir_list, old_file_list = ls_dir(SRC)

    # Get new lists with the parents changed from SRC to DST
    new_dir_list, new_file_list = change_parent(SRC, DST, old_dir_list), change_parent(SRC, DST, old_file_list)

    # Copy files to new destination
    print(f'COPYING {len(old_file_list)} FILES...')
    file_cp_errs = copy_with_progress(old_file_list, new_file_list)
    print(f'All files copied. Errors encountered: {len(file_cp_errs)}')

    # Copy dirs to new destination (only empty dirs should need to be created)
    print(f'COPYING {len(old_dir_list)} DIRECTORIES...')
    dir_cp_errs = copy_with_progress(old_dir_list, new_dir_list)
    print(f'All directories copied. Errors encountered: {len(dir_cp_errs)}', flush=True)

    # Restore metadata to files
    print(f'RESTORING METADATA TO {len(old_file_list)} FILES...')
    check_meta_ls(old_file_list, new_file_list)

    # Restore metadata to folders
    print(f'RESTORING METADATA TO {len(old_dir_list)} DIRECTORIES...')
    check_meta_ls(old_dir_list, new_dir_list)

    print('Done!')
