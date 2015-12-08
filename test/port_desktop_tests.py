#!/usr/bin/env python
#
# title           : port_desktop_tests.py
# description     : Help automate porting of desktop tests to CoreClr.

import argparse
import const
import glob
import json
import os
import re
import shutil
import stat
from string import Template
from subprocess import Popen, PIPE
import sys
import time
import traceback

def GetPrintString(*args):
    return ' '.join(map(str, args))

def Print(*args):
    print (GetPrintString(*args))

def PrintError(*args):
    ''' Mimic the python 3.x print statement (should the community ever go to 3.4, we would not need to change much.)'''
    sys.stderr.write(GetPrintString(*args) + '\n')

def RunProgram(command):
    ''' Run a program and return its exit code, echoing it.
    
        command is a list whose first element is the program
        to run. The remainder of the list is the parameters
        to pass to the program.

        The standard output and error from the program are echoed.
    '''
    Print ('About to execute: ', command)
    p = Popen(command, shell=False, bufsize=0, stderr=PIPE, stdout=PIPE)
    (stdoutdata, stderrdata) = p.communicate()
    error_level = p.returncode
    Print(stdoutdata)
    PrintError(stderrdata)
    return error_level

def filter_define(define):
    ''' Remove CORECLR and DESKTOP as defines, since they are not really used.
    '''
    if define == 'CORECLR':
        return ''
    if define == 'DESKTOP':
        return ''
    return define

def listify(arg):
    ''' Return a list, with arg in it, if not false, otherwise the empty list.
    '''
    result = []
    if arg:
        result.append(arg)
    return result

def parse_line(line, dataset_name, line_num, result):
    ''' Parse the next line in the file.

        If the line is a start line, create a new record and append to end.
        If a continuation line, append additional data.
    '''
    if not line.lstrip():
        # Whitespace line
        return
    parts = line.split('\t')
    num_parts = len(parts)
    if num_parts != 10:
        print("unexpected number of parts = " + str(num_parts))
        return
    if parts[0] == "Test exe":
        return # header line
    testexe = parts[0]

    if not testexe:
        # Maybe continuation?
        num_tests = len(result)
        if num_tests == 0:
            print("continuation line with no prior tests. Line = " + line)
            return
        testdata = result[num_tests - 1]
        defines = parts[6]
        references = parts[7]
        sourcefiles = parts[8]
        extra_flags = filter_define(parts[9])
        if defines:
            testdata['defines'].append(defines)
        if references:
            testdata['references'].append(references)
        if sourcefiles:
            testdata['sourcefiles'].append(sourcefiles)
        if extra_flags:
            testdata['extra_flags'].append(extra_flags)
        return

    # Not a continuation line. make new test data.
    index = len(result)
    testdata = dict(dataset_name=dataset_name,
                    index=index,
                    line_num=line_num,
                    testexe=testexe, 
                    project_file=parts[1],
                    status=parts[2],
                    tool=parts[3],
                    debug=parts[4],
                    optimize=parts[5],
                    defines=listify(parts[6]),
                    references=listify(parts[7]),
                    sourcefiles=listify(parts[8]),
                    extra_flags=listify(filter_define(parts[9])))
    result.append(testdata)
    return

def print_testdata(testdata, indent_columns):
    ''' Print testdata associated with test.

        testdata is a dictionary with the data.
        indent_columns is the number of columns to indent.
    '''
    indents = ' ' * indent_columns
    dataset_name = testdata['dataset_name']
    index = testdata['index']
    if 'line_num' in testdata:
        line_num = testdata['line_num']
    else:
        line_num = ''
    testexe = testdata['testexe']
    project_file = testdata['project_file']
    status = testdata['status']
    tool = testdata['tool']
    debug = testdata['debug']
    optimize = testdata['optimize']
    defines = testdata['defines']
    references = testdata['references']
    sourcefiles = testdata['sourcefiles']
    extra_flags = testdata['extra_flags']
    print('''{indents}({dataset_name}[{index}]#{line_num}, tool={tool}, debug={debug}, optimize = {optimize}, status={status}
{indents}    testexe={testexe}
{indents}    project_file={project_file}
{indents}    defines={defines}
{indents}    references={references}
{indents}    sourcefiles={sourcefiles}
{indents}    extra_flags={extra_flags}
{indents}    )'''.format(**locals()))

def find_fields_with_value(testset, field_set, value):
    '''Add to field_set the names of fields that have
       the given value, for some testdata in the testset.
    '''
    fieldNames = ['testexe', 'project_file', 'status', 'tool', 'debug', 
                  'optimize', 'defines', 'references', 'sourcefiles',
                  'extra_flags']
    for testdata in testset:
        for field in fieldNames:
            if testdata[field] == value:
                field_set.add(field)

def read_test_data(file_path, dataset_name):
    '''Read the test metadata into a list of dictionaries.

    file_path is the path to the test metadata file.
    '''

    result = []
    with open(file_path, 'r') as file:
        line_num = 0
        for line in file:
            line_num += 1
            parse_line (line.rstrip('\n'), dataset_name, line_num, result)
    return result

def get_collected_set_by_tool(testset, tool, name):
    '''From a list of test metadata, get the collected
       union of items from the field with given name.
    '''
    result = set()
    for testdata in testset:
        if testdata['tool'] == tool:
            for item in testdata[name]:
                result.add(item)

    return result

def get_collected_set(testset, name):
    '''From a list of test metadata, get the collected
       union of items from the field with given name.
    '''
    result = set()
    for testdata in testset:
        for item in testdata[name]:
            result.add(item)

    return result

def get_source_files(testset):
    '''From a list of test metadata, get source files used'''
    return get_collected_set(testset, 'sourcefiles')

def get_tobeported_source_files(testset):
    '''From a list of test metadata, get source files used'''
    result = set()
    for testdata in testset:
        if skip_test(testdata):
            continue

        for srcfile in testdata['sourcefiles']:
            result.add(srcfile)

    return result

def report_dataset(caption, testset, source_files, tobeported_source_files):
    print(caption.format(num_tests=len(testset), num_sources=len(source_files), 
                         num_tobeported=len(tobeported_source_files)))

def print_set(the_set, description):
    """ Print a set, using the given descriptor to caption each item.

        Description can reference the item number (item_num) and the
        item (item).
    """
    item_num = -1
    for item in the_set:
        item_num += 1
        print(description.format(item_num=item_num, item=item))

def make_needed_directories(dest_path):
    dest_dir = os.path.dirname(dest_path)
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)

def write_string_to_file(input_string, output_path):
    make_needed_directories(output_path)
    with open(output_path, 'w') as output_file:
        output_file.writelines(input_string)

def copy_source(output_root_path, enlistment_path, source_files):
    ''' Copy source files from the enlistment to the output.
    '''
    if os.path.exists(output_root_path):
        shutil.rmtree(output_root_path, onerror=del_rw)
    for source_file in source_files:
        src_path = os.path.join(enlistment_path, source_file)
        if not os.path.exists(src_path):
            print('Source file {} not found'.format(src_path))
        dest_path = os.path.join(output_root_path, source_file)
        make_needed_directories(dest_path)
        shutil.copyfile(src_path, dest_path)
    return

def copy_test_sources(testdata):
    ''' Copy source files for a test from the enlistment to the output.

        Only copy if the file does not already exist.
        returns True unless all of the source files
        already existed in the destination location.
    '''
    enlistment_path = args.enlistment_path
    output_root_path = args.output_path
    sourcefiles = testdata['sourcefiles']
    files_copied = False
    for source_file in sourcefiles:
        src_path = os.path.join(enlistment_path, source_file)
        if not os.path.exists(src_path):
            print('Source file {} not found'.format(src_path))
            assert False
        dest_path = os.path.join(output_root_path, source_file)
        if not os.path.exists(dest_path):
            make_needed_directories(dest_path)
            shutil.copyfile(src_path, dest_path)
            files_copied = True
    return  files_copied

def scan_source_file(file_path, item):
    ''' Return True iff the given source file contain the item as a substring.
    '''
    with open(file_path, 'r') as file:
        for line in file:
            index = line.find(item)
            if index >= 0:
                return True
    return False

def scan_source_files(testdata, item):
    ''' Return True iff source files for the test contain the item as a substring.
    '''
    enlistment_path = args.enlistment_path
    sourcefiles = testdata['sourcefiles']
    for source_file in sourcefiles:
        src_path = os.path.join(enlistment_path, source_file)
        if not os.path.exists(src_path):
            print('Source file {} not found'.format(src_path))
            assert False
        found = scan_source_file(src_path, item)
        if found:
            return True
    return False


def write_csproj(testdata):
    ''' Write csproj file for given testdata'''

    if testdata['tool'] != 'csc':
        return # Not C#

    project_path = os.path.join(args.output_path, testdata['project_file'])
    relative_project_dir = os.path.dirname(testdata['project_file'])

    # Note: in a Template, if we do not want to expand what follows a dollar
    # we must double the dollar to get a single dollar out.
    csproj_template = Template(
'''<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="12.0" DefaultTargets="Build" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <Import Project="$$([MSBuild]::GetDirectoryNameOfFileAbove($$(MSBuildThisFileDirectory), dir.props))\dir.props" />
  <PropertyGroup>
    <Configuration Condition=" '$$(Configuration)' == '' ">Debug</Configuration>
    <Platform Condition=" '$$(Platform)' == '' ">AnyCPU</Platform>
    <AssemblyName>$$(MSBuildProjectName)</AssemblyName>
    <SchemaVersion>2.0</SchemaVersion>
    <ProjectGuid>{95DFC527-4DC1-495E-97D7-E94EE1F7140D}</ProjectGuid>
    <OutputType>Exe</OutputType>
    <AppDesignerFolder>Properties</AppDesignerFolder>
    <FileAlignment>512</FileAlignment>
    <ProjectTypeGuids>{786C830F-07A1-408B-BD7F-6EE04809D6DB};{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}</ProjectTypeGuids>
    <ReferencePath>$$(ProgramFiles)\Common Files\microsoft shared\VSTT\11.0\UITestExtensionPackages</ReferencePath>
    <SolutionDir Condition="$$(SolutionDir) == '' Or $$(SolutionDir) == '*Undefined*'">..\..\</SolutionDir>
    <RestorePackages>true</RestorePackages>
    <NuGetPackageImportStamp>7a9bfb7d</NuGetPackageImportStamp>
  </PropertyGroup>
  <!-- Default configurations to help VS understand the configurations -->
  <PropertyGroup Condition=" '$$(Configuration)|$$(Platform)' == 'Debug|AnyCPU' ">
  </PropertyGroup>
  <PropertyGroup Condition=" '$$(Configuration)|$$(Platform)' == 'Release|AnyCPU' ">
  </PropertyGroup>
  <ItemGroup>
    <CodeAnalysisDependentAssemblyPaths Condition=" '$$(VS100COMNTOOLS)' != '' " Include="$$(VS100COMNTOOLS)..\IDE\PrivateAssemblies">
      <Visible>False</Visible>
    </CodeAnalysisDependentAssemblyPaths>
  </ItemGroup>
  <PropertyGroup>
    <!-- Set to 'Full' if the Debug? column is marked in the spreadsheet. Leave blank otherwise. -->
    <DebugType>$debug_type</DebugType>$extra_properties
  </PropertyGroup>
  <ItemGroup>
    $compile_sources
  </ItemGroup>
  <ItemGroup>
    <None Include="$$(JitPackagesConfigFileDirectory)$dependencies\project.json" />
    <None Include="app.config" />
  </ItemGroup>
  <ItemGroup>
    <Service Include="{82A7F48D-3B50-4B1E-B82E-3ADA8210C358}" />
  </ItemGroup>
  <PropertyGroup>
    <ProjectJson>$$(JitPackagesConfigFileDirectory)$dependencies\project.json</ProjectJson>
    <ProjectLockJson>$$(JitPackagesConfigFileDirectory)$dependencies\project.lock.json</ProjectLockJson>
  </PropertyGroup>
  <Import Project="$$([MSBuild]::GetDirectoryNameOfFileAbove($$(MSBuildThisFileDirectory), dir.targets))\dir.targets" />
  <PropertyGroup Condition=" '$$(MsBuildProjectDirOverride)' != '' ">
  </PropertyGroup> 
</Project>
''')
    # Variables to set.
    # <DebugType>$debug_type</DebugType>
    # <Optimize>$optimize</Optimize>
    # <CheckForOverflowUnderflow>$checked</CheckForOverflowUnderflow>
    # <NoLogo>$nologo</NoLogo>
    # <NoStandardLib>$nostdlib</NoStandardLib>
    # <Noconfig>$noconfig</Noconfig>
    # <DisabledWarnings>$disabled_warnings</DisabledWarnings>
    # <WarningLevel>$warning_level</WarningLevel>, only if specified.
    # <AllowUnsafeBlocks>$unsafe</AllowUnsafeBlocks>
    # <DefineConstants>$$(DefineConstants);$extra_defines</DefineConstants>

    # First set default values for all.
    debug_type = ''
    checked = ''
    nologo = ''
    nostdlib = ''
    noconfig = ''
    disabled_warnings = ''
    warning_level = -1
    unsafe = ''
    extra_defines = ''
    compile_sources = ''
    dependencies = 'minimal'
    uses_threading = scan_source_files(testdata, 'System.Threading')
    if uses_threading:
        dependencies = 'threading+thread'

    if testdata['debug'] == 'TRUE':
        debug_type = 'FULL'
    
    extra_properties = ''

    if testdata['optimize'] == 'TRUE':
        extra_properties += '''
    <Optimize>True</Optimize>'''
    elif testdata['optimize'] == 'FALSE':
        extra_properties += '''
    <Optimize></Optimize>'''
    elif testdata['optimize'] == '<default>':
        # Omit the <Optimize> tag.
        pass
    else:
        print('Invalid optimize field = ' + testdata['optimize'] + 
              ' for test = ' + testdata['textexe'])
    
    for flag in testdata['extra_flags']:
        flag = flag.strip('"')
        if flag.startswith('/checked'):
            extra_properties += '''
    <CheckForOverflowUnderflow>True</CheckForOverflowUnderflow>'''
        elif flag.startswith('/nologo'):
            extra_properties += '''
    <NoLogo>True</NoLogo>'''
        elif flag.startswith('/nostdlib'):
            extra_properties += '''
    <NoStandardLib>True</NoStandardLib>'''
        elif flag.startswith('/noconfig'):
            extra_properties += '''
    <Noconfig>True</Noconfig>'''
        elif flag.startswith('/nowarn'):
            # Ignore because the ones we care about are in global properties.
            pass
        elif flag.startswith('/w::'):
            # Also ignore setting warning level
            pass
        elif flag.startswith('/unsafe'):
            extra_properties += '''
    <AllowUnsafeBlocks>True</AllowUnsafeBlocks>'''
        elif flag.startswith('/target:'):
            # Ignore as all ours are exe.
            pass
        else:
            print('Unsupported flag = ' + flag + ' in test = ' + testdata['testexe'] + 
                  ', skipping')
            return

    for d in testdata['defines']:
        extra_defines += ';' + d

    if extra_defines:
        extra_properties += '''
    <DefineConstants>$(DefineConstants)''' + extra_defines + '</DefineConstants>'

    for s in testdata['sourcefiles']:
        relative_path = os.path.relpath(path=s, start=relative_project_dir)
        if compile_sources:
            compile_sources = '''
    '''
        compile_sources += '<Compile Include="' + relative_path + '" />'

    csproj_str = csproj_template.substitute(locals())
    write_string_to_file(csproj_str, project_path)

def write_ilproj(testdata):
    ''' Write ilproj file for given testdata'''

    if testdata['tool'] != 'ilasm':
        return # Not il

    project_path = os.path.join(args.output_path, testdata['project_file'])
    relative_project_dir = os.path.dirname(testdata['project_file'])

    # Note: in a Template, if we do not want to expand what follows a dollar
    # we must double the dollar to get a single dollar out.
    ilproj_template = Template(
'''<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="12.0" DefaultTargets="Build" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <Import Project="$$([MSBuild]::GetDirectoryNameOfFileAbove($$(MSBuildThisFileDirectory), dir.props))\dir.props" />
  <PropertyGroup>
    <Configuration Condition=" '$$(Configuration)' == '' ">Debug</Configuration>
    <Platform Condition=" '$$(Platform)' == '' ">AnyCPU</Platform>
    <AssemblyName>$$(MSBuildProjectName)</AssemblyName>
    <SchemaVersion>2.0</SchemaVersion>
    <ProjectGuid>{95DFC527-4DC1-495E-97D7-E94EE1F7140D}</ProjectGuid>
    <OutputType>Exe</OutputType>
    <AppDesignerFolder>Properties</AppDesignerFolder>
    <FileAlignment>512</FileAlignment>
    <ProjectTypeGuids>{786C830F-07A1-408B-BD7F-6EE04809D6DB};{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}</ProjectTypeGuids>
    <ReferencePath>$$(ProgramFiles)\Common Files\microsoft shared\VSTT\11.0\UITestExtensionPackages</ReferencePath>
    <SolutionDir Condition="$$(SolutionDir) == '' Or $$(SolutionDir) == '*Undefined*'">..\..\</SolutionDir>
    <NuGetPackageImportStamp>7a9bfb7d</NuGetPackageImportStamp>
  </PropertyGroup>
  <!-- Default configurations to help VS understand the configurations -->
  <PropertyGroup Condition=" '$$(Configuration)|$$(Platform)' == 'Debug|AnyCPU' ">
  </PropertyGroup>
  <PropertyGroup Condition=" '$$(Configuration)|$$(Platform)' == 'Release|AnyCPU' ">
  </PropertyGroup>
  <ItemGroup>
    <CodeAnalysisDependentAssemblyPaths Condition=" '$$(VS100COMNTOOLS)' != '' " Include="$$(VS100COMNTOOLS)..\IDE\PrivateAssemblies">
      <Visible>False</Visible>
    </CodeAnalysisDependentAssemblyPaths>
  </ItemGroup>
  <PropertyGroup>
    <!-- Set to 'Full' if the Debug? column is marked in the spreadsheet. Leave blank otherwise. -->
    <DebugType>$debug_type</DebugType>
  </PropertyGroup>
  <ItemGroup>
    $compile_sources
  </ItemGroup>
  <ItemGroup>
    <None Include="app.config" />
  </ItemGroup>
  <ItemGroup>
    <Service Include="{82A7F48D-3B50-4B1E-B82E-3ADA8210C358}" />
  </ItemGroup>
  <Import Project="$$([MSBuild]::GetDirectoryNameOfFileAbove($$(MSBuildThisFileDirectory), dir.targets))\dir.targets" />
  <PropertyGroup Condition=" '$$(MsBuildProjectDirOverride)' != '' ">
  </PropertyGroup> 
</Project>
''')
    # Variables to set.
    # <DebugType>$debug_type</DebugType>

    # First set default values for all.
    debug_type = ''
    extra_defines = ''
    compile_sources = ''

    if testdata['debug'] == 'TRUE':
        debug_type = 'FULL'
    
    for s in testdata['sourcefiles']:
        relative_path = os.path.relpath(path=s, start=relative_project_dir)
        if compile_sources:
            compile_sources = '''
    '''
        compile_sources += '<Compile Include="' + relative_path + '" />'

    ilproj_str = ilproj_template.substitute(locals())
    write_string_to_file(ilproj_str, project_path)

def ensure_write_app_config(project_path):
    ''' Ensure there is an app.config file in the directory of a project.
    '''
    project_dir = os.path.dirname(project_path)
    appconfig_path = os.path.join(project_dir, 'app.config')
    if os.path.exists(appconfig_path):
        return
    appconfig_str = '''<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <runtime>
    <assemblyBinding xmlns="urn:schemas-microsoft-com:asm.v1">
      <dependentAssembly>
        <assemblyIdentity name="System.Runtime" publicKeyToken="b03f5f7f11d50a3a" culture="neutral" />
        <bindingRedirect oldVersion="0.0.0.0-4.0.20.0" newVersion="4.0.20.0" />
      </dependentAssembly>
      <dependentAssembly>
        <assemblyIdentity name="System.Text.Encoding" publicKeyToken="b03f5f7f11d50a3a" culture="neutral" />
        <bindingRedirect oldVersion="0.0.0.0-4.0.10.0" newVersion="4.0.10.0" />
      </dependentAssembly>
      <dependentAssembly>
        <assemblyIdentity name="System.Threading.Tasks" publicKeyToken="b03f5f7f11d50a3a" culture="neutral" />
        <bindingRedirect oldVersion="0.0.0.0-4.0.10.0" newVersion="4.0.10.0" />
      </dependentAssembly>
      <dependentAssembly>
        <assemblyIdentity name="System.IO" publicKeyToken="b03f5f7f11d50a3a" culture="neutral" />
        <bindingRedirect oldVersion="0.0.0.0-4.0.10.0" newVersion="4.0.10.0" />
      </dependentAssembly>
      <dependentAssembly>
        <assemblyIdentity name="System.Reflection" publicKeyToken="b03f5f7f11d50a3a" culture="neutral" />
        <bindingRedirect oldVersion="0.0.0.0-4.0.10.0" newVersion="4.0.10.0" />
      </dependentAssembly>
    </assemblyBinding>
  </runtime>
</configuration>
'''
    write_string_to_file(appconfig_str, appconfig_path)

def skip_test(testdata):
    ''' Decide whether to skip processing a test.
    '''
    status = testdata['status']
    if status == 'ported':
        return True
    if status.startswith('do not port:'):
        return True
    if status.startswith('postponed:'):
        return True
    if status.startswith('not ported: has arguments'):
        return True
    if status.startswith('not ported: has references'):
        return True

    project_file = testdata['project_file']
    if project_file == '<not computed>':
        return True
    if len(testdata['sourcefiles']) != 1:
        return True

    if testdata['tool'] == 'csc':
        # return True
        for flag in testdata['extra_flags']:
            flag = flag.strip('"')
            if flag.startswith('/checked'):
                pass
            elif flag.startswith('/nologo'):
                pass
            elif flag.startswith('/nostdlib'):
                pass
            elif flag.startswith('/noconfig'):
                pass
            elif flag.startswith('/nowarn'):
                pass
            elif flag.startswith('/w::'):
                pass
            elif flag.startswith('/unsafe'):
                pass
            elif flag.startswith('/target:'):
                pass
            else:
                # Unsupported flag.
                return True
    else:
        # For first batch, skip asm.
        return True
        # return False

    return False

def write_project_file(testdata):
    project_path = os.path.join(args.output_path, testdata['project_file'])
    ensure_write_app_config(project_path)
    if testdata['tool'] == 'csc':
        write_csproj(testdata)
    elif testdata['tool'] == 'ilasm':
        write_ilproj(testdata)
    pass

def write_project_files():
    test_lists = []
    if args.coreclr_path:
        test_lists.append(coreclrdata)
    if args.desktop_path:
        test_lists.append(desktopdata)

    for test_list in test_lists:
        for testdata in test_list:
            if skip_test(testdata):
                continue
            if check_test_conflict(testdata, False):
                continue

            write_project_file(testdata)

def check_test_conflict(testdata, report):
    ''' Check for conflict between the test and the existing tests.
       
        Returns True if there is a conflict.
    '''
    need_header = report
    result = False

    # Test for project file conflict
    project_path = os.path.join(args.output_path, testdata['project_file'])
    project_exists = os.path.exists(project_path)
    if project_exists:
        if need_header:
            print('for test = ' + testdata['testexe'] + ':')
            need_header = False
        print('    project file already exists: ' + project_path)
        result = True

    # Test for source files already existing
    for source in testdata['sourcefiles']:
        source_path = os.path.join(args.output_path, source)
        if os.path.exists(source_path):
            if need_header:
                print('for test = ' + testdata['testexe'] + ':')
                print('    project file does not exist: ' + project_path)
                need_header = False
            print('        source file already exists: ' + source_path)
            result = True

    return result

def check_test_conflicts():
    test_lists = []
    if args.coreclr_path:
        test_lists.append(coreclrdata)
    if args.desktop_path:
        test_lists.append(desktopdata)

    for test_list in test_lists:
        for testdata in test_list:
            if skip_test(testdata):
                continue
            check_test_conflict(testdata, True)

def tally_testset(testset, testset_name):
    ''' Create maps from testexe and project_file to test ids.
    '''
    exes_map = {}
    projects_map = {}
    index = 0
    for testdata in testset:
        id = [testset_name, index]
        testexe = testdata['testexe']
        project_file = testdata['project_file']
        if not (testexe in exes_map):
            exe_ids = []
            exes_map[testexe] = exe_ids
        else:
            exe_ids = exes_map[testexe]
        exe_ids.append(id)

        if not (project_file in projects_map):
            project_ids = []
            projects_map[project_file] = project_ids
        else:
            project_ids = projects_map[project_file]
        project_ids.append(id)
        index += 1

    return exes_map, projects_map

def print_map_multiple_ids(the_map, map_name):
    ''' Print map entries that have multiple ids.
    '''
    need_header = True
    count = 0
    for key in the_map:
        values = the_map[key]
        if len(values) > 1:
            if need_header:
                print("Multiple-id entries for map {}".format(map_name))
                need_header = False
            print('    ids[{}]: {} -> {}'.format(count, key, values))
            for value in values:
                testset_name, index = value
                if testset_name == 'coreclr':
                    testdata = coreclrdata[index]
                else:
                    testdata = desktopdata[index]
                print_testdata(testdata, 8)
            count += 1

def id_map_join(mapa, mapb):
    join_map = {}
    for key in mapa:
        if key in mapb:
            valuea = mapa[key]
            valueb = mapb[key]
            join_value = valuea + valueb
            join_map[key] = join_value
    return join_map

def check_coreclr_desktop_conflicts():
    if not (args.coreclr_path and args.desktop_path):
        print('check_coreclr_desktop_conflicts requires both args.coreclr_path and args.desktop_path')
        return
    coreclr_exes_map, coreclr_projects_map = tally_testset(coreclrdata, 'coreclr')
    desktop_exes_map, desktop_projects_map = tally_testset(desktopdata, 'desktop')

    print_map_multiple_ids(coreclr_exes_map, 'coreclr_exes_map')
    print_map_multiple_ids(coreclr_projects_map, 'coreclr_projects_map')

    print_map_multiple_ids(desktop_exes_map, 'desktop_exes_map')
    print_map_multiple_ids(desktop_projects_map, 'desktop_projects_map')

    duplicate_exes_map = id_map_join(coreclr_exes_map, desktop_exes_map)
    duplicate_projects_map = id_map_join(coreclr_projects_map, desktop_projects_map)
    print_map_multiple_ids(duplicate_exes_map, 'duplicate_exes_map')
    print_map_multiple_ids(duplicate_projects_map, 'duplicate_projects_map')

    print('Number of coreclr tests = {}'.format(len(coreclrdata)))
    print('Number of coreclr exes = {}'.format(len(coreclr_exes_map)))
    print('Number of coreclr projects = {}'.format(len(coreclr_projects_map)))

    print('Number of desktop tests = {}'.format(len(desktopdata)))
    print('Number of desktop exes = {}'.format(len(desktop_exes_map)))
    print('Number of desktop projects = {}'.format(len(desktop_projects_map)))

    print('Number of duplicate exes = {}'.format(len(duplicate_exes_map)))
    print('Number of duplicate projects = {}'.format(len(duplicate_projects_map)))

    pass

def element_or_blank(list, index):
    ''' Get the element of the list at the index position, if it exists, else blank
    '''
    if index < len(list):
        return list[index]
    return ''

def write_test_data(output_file, testdata):
    ''' Write out tab-separated lines of the data for a test.
    '''
    # Precede with blank line of tabs.
    line = "\t\t\t\t\t\t\t\t\t\n"
    output_file.write(line)

    testexe = testdata['testexe']
    project_file = testdata['project_file']
    status = testdata['status']
    tool = testdata['tool']
    debug = testdata['debug']
    optimize = testdata['optimize']
    defines = testdata['defines']
    references = testdata['references']
    sourcefiles = testdata['sourcefiles']
    extra_flags = testdata['extra_flags']
    line = "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\n".format(
        testexe, project_file, status, tool, debug, optimize,
        element_or_blank(defines, 0), element_or_blank(references, 0),
        element_or_blank(sourcefiles, 0), element_or_blank(extra_flags, 0))
    output_file.write(line)
    max_length = max(len(defines), len(references), 
                     len(sourcefiles), len(extra_flags))

    # Get continuation lines.
    for i in range(1, max_length ):
        line = "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\n".format(
            '', '', '', '', '', '',
            element_or_blank(defines, i), element_or_blank(references, i),
            element_or_blank(sourcefiles, i), element_or_blank(extra_flags, i))
        output_file.write(line)


def write_test_set(path, testset):
    ''' Write updated test set data.
    '''

    new_path = path + ".new"
    header = '''Test exe	Expected project file	Status	Tool	Debug?	Optimize?	Defines	References	SourceFiles	Extra flags
'''
    with open(new_path, 'w') as output_file:
        output_file.write(header)
        for testdata in testset:
            write_test_data(output_file, testdata)

    pass

def id_to_testdata(id):
    dataset_name = id[0]
    index = id[1]
    if dataset_name == 'coreclr':
        dataset = coreclrdata
    else:
        dataset = desktopdata

    testdata = dataset[index]
    return testdata

def check_ids_consistency(project_ids):
    id0 = project_ids[0]
    testdata0 = id_to_testdata(id0)
    testexe0 = testdata0['testexe']
    project_file0 = testdata0['project_file']
    status0 = testdata0['status']
    tool0 = testdata0['tool']
    debug0 = testdata0['debug']
    optimize0 = testdata0['optimize']
    defines0 = set(testdata0['defines'])
    defines0 = defines0 - set(['CORECLR', 'DESKTOP'])
    references0 = set(testdata0['references'])
    sourcefiles0 = set(testdata0['sourcefiles'])
    extra_flags0 = set(testdata0['extra_flags'])
    cummulative_flags = extra_flags0

    num_ids = len(project_ids)
    for i in range(1, num_ids):
        idi = project_ids[i]
        testdatai = id_to_testdata(idi)
        testexei = testdatai['testexe']
        project_filei = testdatai['project_file']
        statusi = testdatai['status']
        tooli = testdatai['tool']
        debugi = testdatai['debug']
        optimizei = testdatai['optimize']
        definesi = set(testdatai['defines'])
        definesi = definesi - set(['CORECLR', 'DESKTOP'])
        referencesi = set(testdatai['references'])
        sourcefilesi = set(testdatai['sourcefiles'])
        extra_flagsi = set(testdatai['extra_flags'])
        ok = True
        bad_fields = []
        if testexe0 != testexei:
            bad_fields.append('testexe')
            ok = False
        if project_file0 != project_filei:
            bad_fields.append('project_file')
            ok = False
        if status0 != statusi:
            bad_fields.append('status')
            ok = False
        if tool0 != tooli:
            bad_fields.append('tool')
            ok = False
        if debug0 != debugi:
            bad_fields.append('debug')
            ok = False
        if optimize0 != optimizei:
            bad_fields.append('optimize')
            ok = False
        if defines0 != definesi:
            bad_fields.append('defines')
            ok = False
        if references0 != referencesi:
            bad_fields.append('references')
            ok = False
        if sourcefiles0 != sourcefilesi:
            bad_fields.append('sourcefiles')
            ok = False
        if cummulative_flags != extra_flagsi:
            bad_fields.append('extra_flags:{}|{}'.format(
                cummulative_flags - extra_flagsi, extra_flagsi - cummulative_flags))
            cummulative_flags |= extra_flagsi
            testdata0['extra_flags'] = cummulative_flags
            testdatai['extra_flags'] = cummulative_flags
            ok = False

        if not ok:
            print('Inconsistent testdata between id[0]={} and id[{}]={}, fields={}'.format(
                id0, i, idi, ' '.join(bad_fields)))
            print_testdata(testdata0, 4)
            print_testdata(testdatai, 4)

        pass

    pass

def check_duplicate_files(id):
    if not args.check_path:
        return

    check_path = args.check_path
    testdata = id_to_testdata(id)
    project_file = testdata['project_file']
    sourcefiles = set(testdata['sourcefiles'])
    project_path = os.path.join(check_path, project_file)
    problem_found = False
    messages = []
    if os.path.exists(project_path):
        messages.append('    Existing project file found: {}'.format(project_path))
        problem_found = True
    project_dir = os.path.dirname(project_path)
    for sourcefile in sourcefiles:
        source_path = os.path.join(check_path, sourcefile)
        source_dir = os.path.dirname(source_path)
        if source_dir != project_dir:
            messages.append('    directory for source file {} does not match project directory {}'.format(
                source_path, project_dir))
            problem_found = True
            assert False
        if os.path.exists(source_path):
            messages.append('    Existing source file found: {}'.format(source_path))
            problem_found = True

    if problem_found:
        print('Problem found for test with id = {}'.format(id))
        for message in messages:
            print(message)
        print_testdata(testdata, 4)

    pass

def update_data(project_ids):
    ''' Update status of the tests to "ported"

        Also assert that other data is the same for them.
    '''
    id0 = project_ids[0]
    testdata0 = id_to_testdata(id0)
    testexe0 = testdata0['testexe']
    project_file0 = testdata0['project_file']
    testdata0['status'] = 'ported'
    status0 = testdata0['status']
    tool0 = testdata0['tool']
    debug0 = testdata0['debug']
    optimize0 = testdata0['optimize']
    defines0 = set(testdata0['defines'])
    defines0 = defines0 - set(['CORECLR', 'DESKTOP'])
    references0 = set(testdata0['references'])
    sourcefiles0 = set(testdata0['sourcefiles'])
    extra_flags0 = set(testdata0['extra_flags'])

    num_ids = len(project_ids)
    for i in range(1, num_ids):
        idi = project_ids[i]
        testdatai = id_to_testdata(idi)
        testexei = testdatai['testexe']
        project_filei = testdatai['project_file']
        testdatai['status'] = 'ported'
        statusi = testdatai['status']
        tooli = testdatai['tool']
        debugi = testdatai['debug']
        optimizei = testdatai['optimize']
        definesi = set(testdatai['defines'])
        definesi = definesi - set(['CORECLR', 'DESKTOP'])
        referencesi = set(testdatai['references'])
        sourcefilesi = set(testdatai['sourcefiles'])
        extra_flagsi = set(testdatai['extra_flags'])
        ok = True
        bad_fields = []
        if testexe0 != testexei:
            bad_fields.append('testexe')
            ok = False
        if project_file0 != project_filei:
            bad_fields.append('project_file')
            ok = False
        if status0 != statusi:
            bad_fields.append('status')
            ok = False
        if tool0 != tooli:
            bad_fields.append('tool')
            ok = False
        if debug0 != debugi:
            bad_fields.append('debug')
            ok = False
        if optimize0 != optimizei:
            bad_fields.append('optimize')
            ok = False
        if defines0 != definesi:
            bad_fields.append('defines')
            ok = False
        if references0 != referencesi:
            bad_fields.append('references')
            ok = False
        if sourcefiles0 != sourcefilesi:
            bad_fields.append('sourcefiles')
            ok = False
        if extra_flags0 != extra_flagsi:
            bad_fields.append('extra_flags:{}|{}'.format(
                extra_flags0 - extra_flagsi, extra_flagsi - extra_flags0))
            ok = False

        if not ok:
            print('Inconsistent testdata between id[0]={} and id[{}]={}, fields={}'.format(
                id0, i, idi, ' '.join(bad_fields)))
            print_testdata(testdata0, 4)
            print_testdata(testdatai, 4)
            assert False

def format_project(testdata):
    if testdata['tool'] != 'csc':
        # Only C# needs formatting
        return

    if not args.codeformatter_path:
        return

    project_path = os.path.join(args.output_path, testdata['project_file'])
    return_code = RunProgram([args.codeformatter_path, project_path])
    if return_code != 0:
        print('Formatting of {} failed with return code {}'.format(project_path, return_code))
    pass

def port_test(id):
    testdata = id_to_testdata(id)
    # files_copied = copy_test_sources(testdata)
    write_project_file(testdata)
    #if files_copied:
    #    format_project(testdata)
    pass

def port_tests():
    test_lists = []
    if args.coreclr_path:
        test_lists.append(coreclrdata)
    if args.desktop_path:
        test_lists.append(desktopdata)

    projects_map = {}

    for test_list in test_lists:
        for testdata in test_list:
            if skip_test(testdata):
                continue

            dataset_name = testdata['dataset_name']
            index = testdata['index']
            project_file = testdata['project_file'].lower()

            id = [dataset_name, index]
            if not (project_file in projects_map):
                project_ids = []
                projects_map[project_file] = project_ids
            else:
                project_ids = projects_map[project_file]
            project_ids.append(id)

    for project_file in projects_map:
        project_ids = projects_map[project_file]
        if len(project_ids) > 1:
            check_ids_consistency(project_ids)
        check_duplicate_files(project_ids[0])

    for project_file in projects_map:
        project_ids = projects_map[project_file]

        update_data(project_ids)
        port_test(project_ids[0])

    pass

def unicode_list_to_string_list(unicode_list):
    string_list = []
    for uvalue in unicode_list:
        svalue = uvalue.encode()
        string_list.append(svalue)
    return string_list

def json_to_testdata(datum, result):
    testdata = {}
    testdata['testexe'] = datum[u'BinPath'].encode()
    testdata['project_file'] = '<not computed>'
    testdata['status'] = 'not ported: from json'
    testdata['tool'] = datum[u'Tool'].encode()
    testdata['debug'] = datum[u'Debug']
    if datum[u'Optimize']:
        testdata['optimize'] = datum[u'Optimize']
    else:
        testdata['optimize'] = ''
    testdata['defines'] = unicode_list_to_string_list(datum[u'Defines'])
    testdata['references'] = unicode_list_to_string_list(datum[u'References'])
    testdata['sourcefiles'] = unicode_list_to_string_list(datum[u'SourceFiles'])
    testdata['extra_flags'] = unicode_list_to_string_list(datum[u'ToolFlags'])
    testdata['index'] = len(result)
    testdata['dataset_name'] = 'json'

    result.append(testdata)
    return testdata

def read_json(file_path):
    result = []
    with open(file_path, 'r') as file:
        json_data = json.load(file)
        for datum in json_data:
            testdata = json_to_testdata(datum, result)

    return result

def main(argv):
    """ Main program for checking one or two test runs. """

    global args, coreclrdata, desktopdata, desktopjson

    # Define return code constants
    const.GeneralError = -1
    const.UnknownArguments = -2

    # Parse the command line    
    parser = argparse.ArgumentParser(description='''Port tests''')
    parser.add_argument('-c', '--coreclr-path', type=str, 
                        help='full path to coreclr jit selfhost test data')
    parser.add_argument('-d', '--desktop-path', type=str, 
                        help='full path to desktop jit selfhost test data')
    parser.add_argument('-j', '--desktop-json-path', type=str, 
                        help='full path to desktop jit self host json test data')
    parser.add_argument('-o', '--output-path', type=str, 
                        help='full path to root directory to which to copy source files')
    parser.add_argument('--check-path', type=str, 
                        help='''full path to root directory to check for existing files.
                           If not given then the --output-path is used. 
                           This is used to check if source or project files already
                           exist. This is useful if we want to use an output path to a
                           temporary location for testing, before actually modifying the
                           actual target location.
                        ''')
    parser.add_argument('--codeformatter-path', type=str, 
                        help='full path to codeformatter')
    parser.add_argument('-e', '--enlistment-path', type=str, 
                        help='full path to root of test sources')
    parser.add_argument('--write-sources', default=False, action="store_true",
                        help='Write source files to output path')
    parser.add_argument('--write-projects', default=False, action="store_true",
                        help='Write project files to output path')
    parser.add_argument('--check-test-conflicts', default=False, action="store_true",
                        help='Check for conflicts between new tests and existing tests')
    parser.add_argument('--check-coreclr-desktop-conflicts', default=False, action="store_true",
                        help='Check for conflicts between coreclr and desktop test data')
    parser.add_argument('--write-test-data', default=False, action="store_true",
                        help='''Write updated test data. Files are same as input with .new at end.''')
    parser.add_argument('--port', default=False, action="store_true",
                        help='''Port tests, making project files and copying sources, also
                                making updated test files.''')
    parser.add_argument('-v', '--verbose', default=False, action="store_true",
                        help='Verbose output')

    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print('Unknown argument(s): ', ', '.join(unknown))
        return const.UnknownArguments
    verbose = args.verbose
    fields_with_default = set()
    fields_with_not_computed = set()
    if args.desktop_json_path:
        desktopjson = read_json(args.desktop_json_path)

    if args.coreclr_path:
        coreclrdata = read_test_data(args.coreclr_path, 'coreclr')
        coreclr_source_files = get_source_files(coreclrdata)
        coreclr_tobeported_source_files = get_tobeported_source_files(coreclrdata)
        coreclr_defines_csc = get_collected_set_by_tool(coreclrdata, 'csc', 'defines')
        coreclr_defines_ilasm = get_collected_set_by_tool(coreclrdata, 'ilasm', 'defines')
        coreclr_extra_flags_csc = get_collected_set_by_tool(coreclrdata, 'csc', 'extra_flags')
        coreclr_extra_flags_ilasm = get_collected_set_by_tool(coreclrdata, 'ilasm', 'extra_flags')
        report_dataset('CoreClr Jit Selfhost, #tests={num_tests}, #source files={num_sources}, #tobeported source files={num_tobeported}', 
                       coreclrdata, coreclr_source_files, coreclr_tobeported_source_files)
        find_fields_with_value(coreclrdata, fields_with_default, '<default>')
        find_fields_with_value(coreclrdata, fields_with_not_computed, '<not computed>')
        if args.write_test_data:
            write_test_set(args.coreclr_path, coreclrdata)

    if args.desktop_path:
        desktopdata = read_test_data(args.desktop_path, 'desktop')
        desktop_source_files = get_source_files(desktopdata)
        desktop_tobeported_source_files = get_tobeported_source_files(desktopdata)
        desktop_defines_csc = get_collected_set_by_tool(desktopdata, 'csc', 'defines')
        desktop_defines_ilasm = get_collected_set_by_tool(desktopdata, 'ilasm', 'defines')
        desktop_extra_flags_csc = get_collected_set_by_tool(desktopdata, 'csc', 'extra_flags')
        desktop_extra_flags_ilasm = get_collected_set_by_tool(desktopdata, 'ilasm', 'extra_flags')
        report_dataset('Desktop Jit Selfhost, #tests={num_tests}, #source files={num_sources}, #tobeported source files={num_tobeported}', 
                       desktopdata, desktop_source_files, desktop_tobeported_source_files)
        find_fields_with_value(desktopdata, fields_with_default, '<default>')
        find_fields_with_value(desktopdata, fields_with_not_computed, '<not computed>')
        if args.write_test_data:
            write_test_set(args.desktop_path, desktopdata)

    print("fields_with_default")
    print_set(fields_with_default, ' '*4 + 'item[{item_num}]={item}')
    print("fields_with_not_computed")
    print_set(fields_with_not_computed, ' '*4 + 'item[{item_num}]={item}')

    if coreclrdata and desktopdata:
        common_source_files = coreclr_source_files & desktop_source_files
        print('#Common source files = {}'.format(len(common_source_files)))
        common_tobeported_source_files = coreclr_tobeported_source_files & desktop_tobeported_source_files
        print('#Common tobeported source files = {}'.format(len(common_tobeported_source_files)))
        combined_source_files = coreclr_source_files | desktop_source_files
        print('#Total source files from spreadsheet = {}'.format(len(combined_source_files)))
        combined_tobeported_source_files = coreclr_tobeported_source_files | desktop_tobeported_source_files
        print('#Total tobeported source files from spreadsheet = {}'.format(len(combined_tobeported_source_files)))
        combined_defines_csc = coreclr_defines_csc | desktop_defines_csc
        combined_defines_ilasm = coreclr_defines_ilasm | desktop_defines_ilasm
        combined_extra_flags_csc = coreclr_extra_flags_csc | desktop_extra_flags_csc
        combined_extra_flags_ilasm = coreclr_extra_flags_ilasm | desktop_extra_flags_ilasm
        print("combined_defines_csc")
        print_set(combined_defines_csc, ' '*4 + 'item[{item_num}]={item}')
        print("combined_defines_ilasm")
        print_set(combined_defines_ilasm, ' '*4 + 'item[{item_num}]={item}')
        print("combined_extra_flags_csc")
        print_set(combined_extra_flags_csc, ' '*4 + 'item[{item_num}]={item}')
        print("combined_extra_flags_ilasm")
        print_set(combined_extra_flags_ilasm, ' '*4 + 'item[{item_num}]={item}')

        if args.output_path and args.write_sources:
            copy_source(args.output_path, args.enlistment_path, combined_tobeported_source_files)
        if args.output_path and args.write_projects:
            write_project_files()
        if args.output_path and args.check_test_conflicts:
            check_test_conflicts()
        if args.check_coreclr_desktop_conflicts:
            check_coreclr_desktop_conflicts()
        if args.port:
            if not args.output_path:
                print("Output path required for --port")
                return const.GeneralError
            port_tests()
            write_test_set(args.coreclr_path, coreclrdata)
            write_test_set(args.desktop_path, desktopdata)

    return 0

if __name__ == '__main__':
    try:
        return_code = main(sys.argv[1:])
    except:
        e = sys.exc_info()[0]
        print('Error: port_desktop_tests.py failed due to ', e)
        return_code = const.GeneralError

    sys.exit(return_code)
