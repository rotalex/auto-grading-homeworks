import argparse
import os
import sys
import string
import random
import re

import numpy as np

from collections import defaultdict, namedtuple
from subprocess import Popen, PIPE

skip_student_list = ["mihai.nan", "roxana.pavelescu1307"]

DuplDetails = namedtuple('DuplDetails', 'file1 lines1 file2 lines2 tokens_count')
VariableDetails = namedtuple('VariableDetails', 'file line name type')
FunctionDetails = namedtuple('FunctionDetails', 'file length name type')

MANUAL_TAG = "[TODO remove if not applicable]" + ("=" * 5)
manually_checked_errors = [
    "-0.1: valori/logica hard-coded",
    "-0.1: nume variabile/functii inadecvate",
    "-0.1: impartit ilogic in functii",
    "-0.1: functii kilometrice",
    "-0.1: cod nefolosit",
]

error_summary_2_natural_language = {
    'DEEP_INDENTATION' : "prea multe nivele de indentare",
    'ELSE_AFTER_BRACE' : "else ar trebui pe aceeasi linie cu acolada",
    'FUNCTION_WITHOUT_ARGS' : "functiile fara parametru ar trebuit sa arate: void func(void)",
    'GLOBAL_INITIALISERS' : "folosirea de variabile globale (neinitializate)",
    #'LEADING_SPACE' : "spatiu la inceput de linie",
    'LINE_SPACING' : "lipsa unei lini libere dupa declarea variabilelor",
    'LONG_LINE' : "linii peste 80 de caractere",
    'LONG_LINE_COMMENT' : "comentarii mai lungi de 80 de caractere",
    'OPEN_BRACE' : "acolada deschisa pusa pe linia urmatoare",
    'POINTER_LOCATION' : "plasarea * in pointeri; gresit: foo* bar -> corect: foo *bar",
    'SPACE_BEFORE_TAB' : "spatiu inainte de tab",
    'SPACING' : "spatiere incorecta (lipsesc spatii dupa \',;{}\' operatori/operanzi)",
    'TRAILING_WHITESPACE' : "trailing whitespace",
    'TRAILING_STATEMENTS': "instructiune pe aceeasi linie cu if",
    'TABSTOP' : "spatii dupa tab",
    #'SUSPECT_CODE_INDENT' : "indentare aiurea la if-else",
    #'CODE_INDENT' : "indentare cu spatii",
}

error_summary_2_penalty = {
    'DEEP_INDENTATION' : 0.1,
    'ELSE_AFTER_BRACE' : 0.0,
    'FUNCTION_WITHOUT_ARGS' : 0.0,
    'GLOBAL_INITIALISERS' : 0.2,
    'LEADING_SPACE' : 0.0,
    'LINE_SPACING' : 0.0,
    'LONG_LINE' : 0.1,
    'LONG_LINE_COMMENT' : 0.0,
    'OPEN_BRACE' : 0.0,
    'POINTER_LOCATION' : 0.0,
    'SPACE_BEFORE_TAB' : 0.0,
    'SPACING' : 0.1,
    'TABSTOP' : 0.0,
    'TRAILING_WHITESPACE' : 0.0,
    'TRAILING_STATEMENTS': 0.1,
    #'SUSPECT_CODE_INDENT' : 0.1,
    #'CODE_INDENT' : 0.0,
}


error_summary_2_penalty_apply_threshold = {
    'DEEP_INDENTATION' : 3,
    'ELSE_AFTER_BRACE' : 0,
    'FUNCTION_WITHOUT_ARGS' : 0,
    'GLOBAL_INITIALISERS' : 2,
    'LEADING_SPACE' : 0,
    'LINE_SPACING' : 0,
    'LONG_LINE' : 4,
    'LONG_LINE_COMMENT' : 0,
    'OPEN_BRACE' : 0,
    'POINTER_LOCATION' : 0,
    'SPACE_BEFORE_TAB' : 0,
    'SPACING' : 10,
    'TABSTOP' : 0,
    'TRAILING_WHITESPACE' : 0,
    'TRAILING_STATEMENTS': 4,
    #'SUSPECT_CODE_INDENT' : 4,
    #'CODE_INDENT' : 4,
}

def ignore_students(student_hw_path):
    in_skip_list = any(skiped_students in student_hw_path for skiped_students in skip_student_list)
    return in_skip_list

def skip_students(student_hw_path):
    contains_space =  "*" in student_hw_path
    return contains_space

def list_files(d):
    return [os.path.join(d, f) for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))]

def list_dirs(d):
    return [os.path.join(d, f) for f in os.listdir(d) if os.path.isdir(os.path.join(d, f))]

def list_sources(d):
    return [os.path.join(d, f) for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)) \
            and (".c" in f or ".h" in f)]

def failed_tests_leaks(student_files_output_path):
    points = 0
    leaks = 0
    try:
        with open(student_files_output_path, "r") as file:
            lines = file.readlines()
            leaks = 0
            for idx, line in enumerate(lines):
                prev_test_passed = False
                if idx < len(lines) - 1:
                    prev_test_passed = int("PASSED" in lines[idx + 1])
                leaks += int(line == "Memory leaks\n") * prev_test_passed

                points = int(lines[-1].split("=")[1])
    except (ValueError, IndexError, FileNotFoundError) as e:
        pass
    return 110 - points, leaks

def assess_leaks_failed_tests(grade_file, student_hw_path, verbose=True):
    failed, leaks = failed_tests_leaks(student_hw_path + "/current/results/run-stdout.vmr")
    if failed > 0:
        line = "-%0.1f: teste picate\n" % (failed / 10.0)
        grade_file.write(line)
    if leaks > 0:
        leak_penalty = leaks / 20.0 * (110 - failed) / 100
        line = "-%0.1f: leak-uri de memorie\n" % (leak_penalty)
        grade_file.write(line)

    if verbose:
        print("<failed: %3.1lf leaks: %2.1lf>\t" % (failed, leaks), end="")

def run_checkpatch(file_absolute_path):
    process = Popen(["./checkpatch_wrapper.sh", file_absolute_path], stdout=PIPE)
    (output, err) = process.communicate()
    exit_code = process.wait()
    return output

def run_check_per_stud(student_files_path):
    warnings = defaultdict(lambda:[])
    errors = defaultdict(lambda:[])
    file_count = 0
    binary_files = 0

    for source_file_path in list_sources(student_files_path):
        file_count += 1
        ext = source_file_path[-2:]
        output = run_checkpatch(source_file_path)
        output = str(output).split("\\n")
        for check_line in output:
            parts = check_line.split(ext)
            k = check_line.rfind(ext)
            parts = check_line[:k], check_line[k + len(ext):]
            if len(parts) != 2:
                continue
            src_file, details = parts
            src_file = src_file.split("/")[-1] + ext
            tokens = details.split(":")
            if len(tokens) < 3:
                continue
            store_dict = warnings
            if tokens[2] == ' ERROR':
                store_dict = errors

            store_dict[tokens[3]].append((src_file + ":" + tokens[1], tokens[4]))

    if "SPACING" in warnings:
        del warnings['SPACING']

    return warnings, errors, file_count

def absolute_subsampling(lst, count = 2):
    lst = [sample[0] for sample in lst]
    count = min(len(lst), count)
    if count <= 0:
        return ""
    samples = np.random.choice(lst, count)
    samples = set(samples)
    return " ".join(samples)

def output_check_summary(file, summary, allowed_penalty = 0.5, warning = False):
    human_understandable = error_summary_2_natural_language
    penalty_table = error_summary_2_penalty
    penalty_threshold = error_summary_2_penalty_apply_threshold

    cumulated_penalty = 0.0
    for problem_summary in summary:
        if problem_summary not in human_understandable \
            or problem_summary not in penalty_table \
            or problem_summary not in penalty_threshold:
            continue
        problem_occurences = summary[problem_summary]

        if cumulated_penalty + penalty_table[problem_summary] > allowed_penalty or \
            len(problem_occurences) <= penalty_threshold[problem_summary]:
            penalty = 0.0
        else:
            penalty = penalty_table[problem_summary]

        line = "-%2.1f: %s X %d e.g. %s\n" % (penalty, human_understandable[problem_summary], \
            len(problem_occurences), absolute_subsampling(problem_occurences))
        cumulated_penalty += penalty
        file.write(line)
    return cumulated_penalty

def assess_coding_style(grade_file, student_hw_path, verbose=True):
    line = "+1.0: rezervat coding style & readme\n"
    grade_file.write(line)

    total_pen = 0
    warnings, errors, file_count = run_check_per_stud(student_hw_path + "/current/git/archive")
    total_pen += output_check_summary(grade_file, warnings, 0.5, warning = True)
    total_pen += output_check_summary(grade_file, errors, 0.5 - total_pen)

    if (file_count == 1):
        line = "-0.0: toata implementarea intr-un singur fisier sursa\n"
        grade_file.write(line)

    if verbose:
        print("<style errors & warnings: %2.1lf>\t" % (total_pen), end="")
    return total_pen

def compile_warnings(student_files_build_output_path):
    warnings = 0
    try:
        with open(student_files_build_output_path, "r") as file:
            lines = file.readlines()
            warnings = 0
            for line in lines:
                warnings += int("warning:" in line)
    except FileNotFoundError as e:
        pass
    return warnings

def assess_compile_warnings(grade_file, student_hw_path, verbose=True):
    COMPILATION_WARNINGS_PENALTY = 0.0
    cwarns = compile_warnings(student_hw_path + "/current/results/run-stderr.vmr")
    if cwarns > 0:
        line = "-%1.1f: warning-uri la compilare\n" % (COMPILATION_WARNINGS_PENALTY)
        grade_file.write(line)

    if verbose:
        print("<compilation: %.1lf>\t" % (cwarns), end="")

def check_for_readme(student_files_readme_dir):
    readme_size = 0
    contains_feedback = False
    for source_file_path in list_files(student_files_readme_dir):
        if "readme" in source_file_path.lower():
            readme_size = os.stat(source_file_path).st_size
            try:
                readme_content = open(source_file_path, "r").read()
                contains_feedback = "feedback" in readme_content or \
                                    "Feedback" in readme_content or \
                                    "FEEDBACK" in readme_content
            except:
                pass
    return readme_size, contains_feedback

def assess_readme(grade_file, student_hw_path, verbose=True):
    readme_size, contains_feedback = check_for_readme(student_hw_path + "/current/git/archive");

    if (readme_size <= 1024):
        line = "-0.1: readme necorespunzator (lipsa/scurt & scris in graba)\n"
        grade_file.write(line)

    if contains_feedback:
        line = "+0.0: Multumim pentru feedback ! \(ᵔᵕᵔ)/\n"
        grade_file.write(line)

    if verbose:
        log_readme = "<readme: " + str(readme_size) + "> " + ("F" if contains_feedback else "")
        log_readme += " " * (20 - len(log_readme))
        print(log_readme, end="\t")

def check_arh_structure(student_files_path):
    unrelated_files = 0
    sources = set(list_sources(student_files_path))
    for source_file_path in list_files(student_files_path):
        if source_file_path in sources or "readme" in source_file_path.lower() \
            or "makefile" in source_file_path.lower():
            continue
        unrelated_files += 1
    return unrelated_files

def asses_arh_content(grade_file, student_hw_path, verbose = True):
    unrelated_files = check_arh_structure(student_hw_path +  "/current/git/archive")
    if verbose:
        print("<unrelated files:", unrelated_files, ">\t", end="")
    if unrelated_files > 0:
        line = "-0.0: arhiva contine fisiere ce nu sunt surse/Readme/Makefile (╯°□°）╯︵ ┻━┻\n"
        grade_file.write(line)

def run_similary_check_cmd(student_files_path):
    sources_paths = student_files_path + "/current/git/archive/"
    cmd_line = ["sim_c", "-w100", "-a", "-R", "-n", "-f", sources_paths]
    process = Popen(cmd_line, stdout=PIPE)
    (output, err) = process.communicate()
    exit_code = process.wait()
    return output

def overlaps(a, b):
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))

def interval_size(i):
    return i[1] - i[0]

def check_code_similarity(student_hw_path):
    duplications = run_similary_check_cmd(student_hw_path)
    duplications = str(duplications).split("\\n")
    delimiters = ["archive", "|", "line"]
    regex = '|'.join(map(re.escape, delimiters))

    def summarize_dup(tokens):
        if len(tokens) < 6:
            return
        try:
            file1 = tokens[1][1:-2]
            lines1 = tuple(map(int, tokens[2].split("-")))

            file2 = tokens[4][1:-2]
            lines2, token_count = tokens[5][:-1].split("[")
            lines2 = tuple(map(int, lines2.split("-")))
            token_count = int(token_count)
        except RuntimeError as e:
            print("Error parsing similiarity tool output")
        return DuplDetails(file1, lines1, file2, lines2, token_count)

    def is_valid_duplication(details):
        DUPLICATED_LINES_COUNT_THRESHOLD = 5
        DUPLICATED_TOKENS_COUNT_THRESHOLD = 10

        if details is None:
            return False

        ignorable = False
        ignorable_contained_tokens = [".ref", "tests/", "test", ".in", "~", ".txt", ".pdf", ".py", ".sh"]
        for token in ignorable_contained_tokens:
            ignorable = ignorable or (token in details.file1 or token in details.file2)
        if ignorable:
            return False

        if min(interval_size(details.lines1), interval_size(details.lines2)) <= DUPLICATED_LINES_COUNT_THRESHOLD:
            return False

        if details.file1 == details.file2 and overlaps(details.lines1, details.lines2) > 0:
            return False

        if details.tokens_count <= DUPLICATED_TOKENS_COUNT_THRESHOLD:
            return False

        return True

    signficant_duplicated_patches = []
    for duplication_line in duplications:
        duplication_summary = summarize_dup(re.split(regex, duplication_line))
        if is_valid_duplication(duplication_summary):
            signficant_duplicated_patches.append(duplication_summary)

    return signficant_duplicated_patches

def asses_duplication(grade_file, student_hw_path, verbose = True):
    DUPLICATED_CODE_PATCHES_COUNT_THRESHOLD = 0
    similar_pathes_detail_list = check_code_similarity(student_hw_path)
    duplicated_lines = 0

    if len(similar_pathes_detail_list) >= DUPLICATED_CODE_PATCHES_COUNT_THRESHOLD:
        human_readable_summaries = []
        for duplicated_patch in similar_pathes_detail_list:
            human_readable_summaries.append(["%s:%s %s%s;" % (duplicated_patch.file1,
                "%d-%d" % duplicated_patch.lines1,
                duplicated_patch.file2 + ":" if duplicated_patch.file1 != duplicated_patch.file2 else "",
                "%d-%d" % duplicated_patch.lines2)])

            duplicated_lines += min(interval_size(duplicated_patch.lines1),
                                            interval_size(duplicated_patch.lines2))

        occurences_txt = absolute_subsampling(human_readable_summaries, 5)
        penalty = 0.2 if duplicated_lines > 50 else 0.0
        duplicated_lines = (duplicated_lines // 20 + 1) * 20
        line = "-%.1lf: logica/cod duplicat (~%d linii) e.g:%s\n" % (penalty, duplicated_lines, occurences_txt)
        grade_file.write(line)

        if verbose:
            print("<duplicated loc:%6d>\t" % (duplicated_lines), end="")

def assess_manual_only_checkables(grade_file, student_hw_path, verbose = True):
    grade_file.write("\n")
    for manually_checked_error in manually_checked_errors:
        spaces = (40 - len(manually_checked_error)) * " "
        grade_file.write(manually_checked_error + spaces + MANUAL_TAG + "\n");

def run_ast_generation(files_absolute_path):
    # These are just some keywords that are manually selected and seemed to work
    # just to extract functions names and variables names from code ast.
    filter_in_tokens = ["FunctionDecl", "VarDecl", "DeclStmt", "RecordDecl", "FieldDecl", "TypedefDecl", "ParmVarDecl"]
    filter_out_tokens = ["extern", "__", "\'/lib/clang\'", "\'/usr/include/\'", "\'<invalid sloc>\'"]

    def parse_decl(raw_clang_parser_line):
        pass

    def parse_variable(raw_clang_parser_line, aprox_line):
        return None
        split_token = "used"
        parts = raw_clang_parser_line.split(split_token)[1].strip()
        piv1, piv2 = parts.index(" "), parts.rindex("\'")
        name, type, _ = parts[:piv1].strip(), parts[piv1 + 1:piv2 + 1].strip(), parts[piv2 + 1:].strip()
        return VariableDetails(files_absolute_path, aprox_line, name, type)

    def parse_function(raw_clang_parser_line):
        print(raw_clang_parser_line)
        if "main" in raw_clang_parser_line:
            spl_idx = len("main 'int (int, char **)")
            line_info, name_type_info = raw_clang_parser_line[:-spl_idx], raw_clang_parser_line[-spl_idx - 1:]
        else:
            split_token = "used"
            line_info, name_type_info = raw_clang_parser_line.split(split_token)

        line_marks = line_info.strip().split("line")[1:3]
        [start, end] = [int(l.strip().split(":")[1]) for l in line_marks]

        name_type_info = name_type_info.strip()
        i = name_type_info.index(" ")
        name, type = name_type_info[:i].strip(), name_type_info[i:].strip()

        print(f"{start}|{end}|{name}|{type}")
        #piv1, piv2 = parts.index(" "), parts.rindex("\'")
        # 'file length name type')
        return FunctionDetails(files_absolute_path, end - start, name, type)

    command_ast = "clang -Xclang -ast-dump -fsyntax-only " + files_absolute_path\
        + " | grep -e " + " -e ".join(filter_in_tokens)\
        + " | grep -v -e " + " -e ".join(filter_out_tokens)

    color_codes_escape = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')
    out = os.popen(command_ast).read()
    enable_processing = False # This flag is enabled when a certain line is seen so we don't process shit that we shouldn't

    for output_line in str(out).split("\n"):
        enable_processing = enable_processing or (files_absolute_path in output_line)
        if not enable_processing:
            continue
        try:
            output_line = color_codes_escape.sub('', output_line)
            split_idx = output_line.find('-')
            output_line = output_line[split_idx + 1:]
            #print(output_line)

            if output_line.startswith("DeclStmt"):
                parse_decl(output_line)
            if output_line.startswith("VarDecl"):
                parse_variable(output_line, 0)
            if output_line.startswith("FunctionDecl"):
                parse_function(output_line)
        except Exception as e:
            pass
            #print("Error parsing ast output:", e)


def asses_vars_and_funcs_namings(grade_file, student_hw_path, verbose = True):
    for source_file_path in list_sources(student_hw_path + "/current/git/archive/"):
        run_ast_generation(source_file_path)

def process_student(student_hw_path, ta, grade_folder, verbose = True):
    student_id = student_hw_path.split("/")[-1]
    print(ta, ":\t", student_id + " " * (35 - len(student_hw_path)), end="\t")

    grade_file = open(grade_folder + "/" + student_id, "w")
    try:
        #assess_leaks_failed_tests(grade_file, student_hw_path, verbose)
        #assess_coding_style(grade_file, student_hw_path, verbose)

        asses_vars_and_funcs_namings(grade_file, student_hw_path, verbose)

        #asses_duplication(grade_file, student_hw_path, verbose)
        #assess_compile_warnings(grade_file, student_hw_path, verbose)
        #assess_readme(grade_file, student_hw_path, verbose)
        #asses_arh_content(grade_file, student_hw_path, verbose)
        #assess_manual_only_checkables(grade_file, student_hw_path, verbose)
    except UnicodeDecodeError:
        grade_file.write("[TODO check manually]\n");
    grade_file.write("%s\n" % (ta))
    grade_file.close()

    print("")

def grade(args):
    to_skip_messages = []
    to_grade_list = {}

    for ta in args.teaching_assistants:
        to_grade_list[ta] = open("to_grade." + ta, "w")

    for (idx, stud_path) in enumerate(list_dirs(args.assignments_path)):
        ta = args.teaching_assistants[idx % len(args.teaching_assistants)]

        if skip_students(stud_path):
            line = ta + " skipping " + stud_path + "-> check manually!"
            to_skip_messages.append(line)
            continue
        elif ignore_students(stud_path):
            continue

        process_student(stud_path, ta, args.grade, args.verbose)
        to_grade_list[ta].write(stud_path.split("/")[-1]+"\n")

        if idx % args.print_delim_every == 0:
            print("-" * 200)

    for skip_message in to_skip_messages:
        print(skip_message)

def stat(args):
    count_perfect = 0
    count = 0
    total_points = 0
    total_leaks = 0
    for (idx, stud_path) in enumerate(list_dirs(args.assignments_path)):
        failed = 0
        leaks = 0
        try:
            failed, leaks = failed_tests_leaks(stud_path + "/current/results/run-stdout.vmr")
        except IndexError:
            print("Error processing :", stud_path)
        count += 1
        count_perfect += (failed == 0)
        total_points += (110 - failed)
        total_leaks += leaks
    percentage = int(count_perfect / count * 100.0)
    print("Complete Hw Percentage = ", count_perfect, "/", count, " -> %d%%" % (percentage))
    print("Average grade : %3.1lf" % (total_points / count))
    print("Average amount of leaks : %3.1lf" % (total_leaks / count))

def main():
    parser = argparse.ArgumentParser(description='Automatic grade of student homeworks. \
            Generates a file in grade.vmr format for each student found in homeworks path.')
    parser.add_argument('--assignments_path', metavar='input', type=str,
                        default="hws/1-list/",
                        help='A path towards the homeworks of the students.')
    parser.add_argument('--grade', default="grades/", metavar="output_dir",
                        help="Destination directory for generated grade files.")
    parser.add_argument("--verbose", action='store_true')
    parser.add_argument("--print_delim_every", type=int, default=5, metavar='inteval')
    parser.add_argument("--generate_grading_list", action='store_true',
                        help='Whether to generate a list of student that should be graded by"\
                        "each teaching assitant')
    parser.add_argument("--stat", action='store_true',
                        help="Computes average points, average leaks..")
    parser.add_argument("--teaching_assistants", nargs="+", default=['RAA', 'PR'], metavar='ta',
                        type=str, help="The teaching assistants responsible for this assignment.")

    args = parser.parse_args()

    if args.stat:
        stat(args)
    else:
        grade(args)

if __name__ == "__main__":
    main()
