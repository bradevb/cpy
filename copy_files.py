import fnmatch
import os
import subprocess
import sys
import traceback

from diskcache import Cache
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
        prev_err = prog_cache.get(src)

        try:
            # Check and see if src has errored before, and if it's gone over attempts limit.
            if prev_err is not None and prev_err['attempts'] >= ATTEMPTS:
                print(f"File {src} has reached its attempt limit. "
                      f"Try manually copying this file, or investigate what's going wrong.")
                continue

            if not os.path.exists(dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                cp(src, dst)
            prog_cache.delete(src)
        except Exception as e:
            if prev_err is None:
                prog_cache.set(src, {'src': src, 'dst': dst, 'attempts': 1,
                                     'exception': e, 'traceback': traceback.format_exc()})
            elif prev_err['attempts'] < ATTEMPTS:
                prev_err['attempts'] += 1
                prog_cache.set(src, prev_err)

            errs.append(src)

        finally:
            yield idx, errs


def ls_dir(dir_path, exclusions, verbose=False):
    """Returns a list of all directories, and files in a directory (recursively)."""

    def check_exclusions(root, ls, res_ls):
        """Checks all elements in ls for exclusions. If things aren't excluded, they're appended to res_ls."""

        for cur in ls:
            p = os.path.join(root, cur)
            if exclude_path(cur, exclusions):
                if verbose:
                    print(f'Excluding {p}')
                continue
            else:
                res_ls.append(p)

    dirs_result = []
    files_result = []

    # Append paths to all files and dirs to results
    for root, dirs, files in os.walk(dir_path):
        if exclude_path(root, exclusions):
            continue

        # Check dirs for exclusions
        check_exclusions(root, dirs, dirs_result)

        # Check files for exclusions
        check_exclusions(root, files, files_result)

    return dirs_result, files_result


def exclude_path(path, exclusions):
    """
    Takes a list of exclusion wildcard patterns and returns True if a path matches one.
    So, if this returns True, the path should be excluded.
    """
    for pat in exclusions:
        if fnmatch.fnmatchcase(path, pat):
            return True
    return False


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


def check_meta(src, dst):
    """Checks src's metadata against dst's."""

    def clean_meta_dict(meta):
        """Takes a meta dict from osxmetadata.asdict and removes the keys starting with _."""
        result = {}
        for key, value in meta.asdict(True, True).items():
            if not key.startswith("_"):
                # skip private keys like _version and _filepath
                result[key] = value

        return result

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
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-r', '--reset', help='reset the failed file database', action='store_true')
    args = parser.parse_args()
    # The parent folder to be copied
    SRC = '/Volumes/Archive/GRAPHIC RESOURCES'
    # The folder to copy to
    DST = '/Volumes/test/copy_files'
    # The progress file
    # PROG_FILE = os.path.join(SRC, '.cp_progress')
    # prog_cache = Cache(PROG_FILE)
    prog_cache = Cache('cp_progress')
    # List of file wildcards to exclude
    EXCLUSIONS = ['.cp_progress', 'Thumbs.db']
    # Number of attempts to retry failed files
    ATTEMPTS = 3

    if args.reset:
        print('Resetting failed file database...')
        prog_cache.clear()

    print(f'Copying folder {SRC} to {DST}')
    proceed = input('Does this look correct? y/n: ').lower()
    if proceed != 'y':
        print('Exiting.')
        sys.exit(1)

    print(f'Getting list of directories and files in {SRC}...')
    old_dir_list, old_file_list = ls_dir(SRC, EXCLUSIONS, verbose=True)

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

    # Retry until all files and dirs have been copied or until files reach attempt limit
    print(f'Retrying files and directories with errors up to {ATTEMPTS} attempts...')

    c = 0
    while c < ATTEMPTS or True:
        # Retry files that are under the attempt limit
        combined_errs = [prog_cache.get(x) for x in prog_cache.iterkeys()]

        src_retries = [d['src'] for d in combined_errs if d['attempts'] < ATTEMPTS]
        dst_retries = [d['dst'] for d in combined_errs if d['attempts'] < ATTEMPTS]

        print(f'{len(src_retries)} files/directories to be retried.')
        if not copy_with_progress(src_retries, dst_retries):
            print('All files/directories have been copied or have reached their error limit.')
            break

    # Filter out files that didn't make it from old and new file/dir lists before metadata copy
    old_list = old_file_list + old_dir_list
    new_list = new_file_list + new_dir_list
    for key in prog_cache.iterkeys():
        err = prog_cache.get(key)
        old_list.remove(err['src'])
        new_list.remove(err['dst'])

    # Restore metadata to files/dirs
    print(f'RESTORING METADATA TO {len(old_list)} FILES/DIRECTORIES...')
    check_meta_ls(old_list, new_list)

    print('Done!')
