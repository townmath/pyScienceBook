"""A special directive for including a matplotlib plot.

Given a path to a .py file, it includes the source code inline, then:

- On HTML, will include a .png with a link to a high-res .png.

- On LaTeX, will include a .pdf

This directive supports all of the options of the `image` directive,
except for `target` (since plot will add its own target).

Additionally, if the :include-source: option is provided, the literal
source will be included inline, as well as a link to the source.

The set of file formats to generate can be specified with the
plot_formats configuration variable.
"""

import sys, os, glob, shutil, hashlib, imp, warnings
from io import BytesIO as cStringIO #??
import re
try:
    from hashlib import md5
except ImportError:
    from md5 import md5
from docutils.parsers.rst import directives
try:
    # docutils 0.4
    from docutils.parsers.rst.directives.images import align
except ImportError:
    # docutils 0.5
#    from docutils.parsers.rst.directives.images import Image
#    align = Image.align
    from docutils.parsers.rst.directives.images import Figure
    align = Figure.align
from docutils import nodes
import sphinx

sphinx_version = sphinx.__version__.split(".")
# The split is necessary for sphinx beta versions where the string is
# '6b1'
sphinx_version = tuple([int(re.split('[a-z]', x)[0])
                        for x in sphinx_version[:2]])

import matplotlib
import matplotlib.cbook as cbook
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.image as image
from matplotlib import _pylab_helpers

#import matplotlib.sphinxext.only_directives #?? replacement?

if hasattr(os.path, 'relpath'):
    relpath = os.path.relpath
else:
    def relpath(target, base=os.curdir):
        """
        Return a relative path to the target from either the current dir or an optional base dir.
        Base can be a directory specified either as absolute or relative to current dir.
        """

        if not os.path.exists(target):
            raise OSError('Target does not exist: '+target)

        if not os.path.isdir(base):
            raise OSError('Base is not a directory or does not exist: '+base)

        base_list = (os.path.abspath(base)).split(os.sep)
        target_list = (os.path.abspath(target)).split(os.sep)

        # On the windows platform the target may be on a completely different drive from the base.
        if os.name in ['nt','dos','os2'] and base_list[0] != target_list[0]:
            raise OSError('Target is on a different drive to base. Target: '+target_list[0].upper()+', base: '+base_list[0].upper())

        # Starting from the filepath root, work out how much of the filepath is
        # shared by base and target.
        for i in range(min(len(base_list), len(target_list))):
            if base_list[i] != target_list[i]: break
        else:
            # If we broke out of the loop, i is pointing to the first differing path elements.
            # If we didn't break out of the loop, i is pointing to identical path elements.
            # Increment i so that in all cases it points to the first differing path elements.
            i+=1

        rel_list = [os.pardir] * (len(base_list)-i) + target_list[i:]
        if rel_list:
            return os.path.join(*rel_list)
        else:
            return ""

def write_char(s):
    sys.stdout.write(s)
    sys.stdout.flush()

options = {'alt': directives.unchanged,
           'height': directives.length_or_unitless,
           'width': directives.length_or_percentage_or_unitless,
           'scale': directives.nonnegative_int,
           'align':  directives.unchanged,
           'class': directives.class_option,
           'include-source': directives.flag,
           'encoding': directives.encoding}

template = """
.. htmlonly::

   [%(links)s]

   .. figure:: %(prefix)s%(tmpdir)s/%(outname)s.png
   %(options)s

.. latexonly::
   .. figure:: %(prefix)s%(tmpdir)s/%(outname)s.pdf
   %(options)s
"""

exception_template = """
.. htmlonly::

   [`source code <%(linkdir)s/%(basename)s.py>`__]

Exception occurred rendering plot.

"""

def out_of_date(original, derived):
    """
    Returns True if derivative is out-of-date wrt original,
    both of which are full file paths.
    """
    return (not os.path.exists(derived))
    # or os.stat(derived).st_mtime < os.stat(original).st_mtime)

def runfile(fullpath):
    """
    Import a Python module from a path.
    """
    # Change the working directory to the directory of the example, so
    # it can get at its data files, if any.
    pwd = os.getcwd()
    path, fname = os.path.split(fullpath)
    sys.path.insert(0, os.path.abspath(path))
    stdout = sys.stdout
    sys.stdout = cStringIO.StringIO()
    os.chdir(path)
    try:
        fd = open(fname)
        module = imp.load_module("__main__", fd, fname, ('py', 'r', imp.PY_SOURCE))
    finally:
        del sys.path[0]
        os.chdir(pwd)
        sys.stdout = stdout
    return module

def makefig(fullpath, code, outdir):
    """
    run a pyplot script and save the low and high res PNGs and a PDF in _static
    """
    formats = [('png', 80), ('hires.png', 200), ('pdf', 50)]

    fullpath = str(fullpath)  # todo, why is unicode breaking this
    basedir, fname = os.path.split(fullpath)
    basename, ext = os.path.splitext(fname)

    if str(basename) == "None":
        import pdb
        pdb.set_trace()

    all_exists = True

    # Look for single-figure output files first
    for format, dpi in formats:
        outname = os.path.join(outdir, '%s.%s' % (basename, format))
        if out_of_date(fullpath, outname):
            all_exists = False
            break

    if all_exists:
        write_char('.' * len(formats))
        return 1

    # Then look for multi-figure output files, assuming
    # if we have some we have all...
    i = 0
    while True:
        all_exists = True
        for format, dpi in formats:
            outname = os.path.join(outdir, '%s_%02d.%s' % (basename, i, format))
            if out_of_date(fullpath, outname):
                all_exists = False
                break
        if all_exists:
            i += 1
        else:
            break

    if i != 0:
        write_char('.' * i * len(formats))
        return i

    # We didn't find the files, so build them

    plt.close('all')    # we need to clear between runs
    matplotlib.rcdefaults()
    # Set a figure size that doesn't overflow typical browser windows
    matplotlib.rcParams['figure.figsize'] = (5.5, 4.5)

    if code is not None:
        exec(code)
    else:
        try:
            runfile(fullpath)
        except:
            s = cbook.exception_to_str("Exception running plot %s" % fullpath)
            warnings.warn(s)
            return 0

    fig_managers = _pylab_helpers.Gcf.get_all_fig_managers()
    for i, figman in enumerate(fig_managers):
        for format, dpi in formats:
            if len(fig_managers) == 1:
                outname = basename
            else:
                outname = "%s_%02d" % (basename, i)
            outpath = os.path.join(outdir, '%s.%s' % (outname, format))
            try:
                figman.canvas.figure.savefig(outpath, dpi=dpi)
            except:
                s = cbook.exception_to_str("Exception running plot2 %s" % fullpath)
                warnings.warn(s)
                return 0

            write_char('*')

    return len(fig_managers)

def plot2_directive(name, arguments, options, content, lineno,
                   content_offset, block_text, state, state_machine):
    """
    Handle the plot2 directive.
    """
    formats = setup.config.plot2_formats
    if type(formats) == str:
        formats = eval(formats)

    # The user may provide a filename *or* Python code content, but not both
    if len(arguments) == 1:
        reference = directives.uri(arguments[0])
        basedir, fname = os.path.split(reference)
        basename, ext = os.path.splitext(fname)
        basedir = relpath(basedir, setup.app.builder.srcdir)
        if len(content):
            raise ValueError("plot2 directive may not specify both a filename and inline content")
        content = None
    else:
        basedir = "inline"
        content = '\n'.join(content)
        # Since we don't have a filename, use a hash based on the content
        reference = basename = md5(content).hexdigest()[-10:]
        fname = None

    # Get the directory of the rst file, and determine the relative
    # path from the resulting html file to the plot2_directive links
    # (linkdir).  This relative path is used for html links *only*,
    # and not the embedded image.  That is given an absolute path to
    # the temporary directory, and then sphinx moves the file to
    # build/html/_images for us later.
    rstdir, rstfile = os.path.split(state_machine.document.attributes['source'])
    outdir = os.path.join('plot2_directive', basedir)
    reldir = relpath(setup.confdir, rstdir)
    linkdir = os.path.join(reldir, outdir)

    # tmpdir is where we build all the output files.  This way the
    # plots won't have to be redone when generating latex after html.

    # Prior to Sphinx 0.6, absolute image paths were treated as
    # relative to the root of the filesystem.  0.6 and after, they are
    # treated as relative to the root of the documentation tree.  We need
    # to support both methods here.
    tmpdir = os.path.join('build', outdir)
    tmpdir = os.path.abspath(tmpdir)
    if sphinx_version < (0, 6):
        prefix = ''
    else:
        prefix = '/'
    if not os.path.exists(tmpdir):
        cbook.mkdirs(tmpdir)

    # destdir is the directory within the output to store files
    # that we'll be linking to -- not the embedded images.
    destdir = os.path.abspath(os.path.join(setup.app.builder.outdir, outdir))
    if not os.path.exists(destdir):
        cbook.mkdirs(destdir)

    # Generate the figures, and return the number of them
    num_figs = makefig(reference, content, tmpdir)

    lines = [] #kl
    if options.has_key('include-source'):
        if content is None:
            lines = [
                '.. include:: %s' % os.path.join(setup.app.builder.srcdir, reference),
                '    :literal:']
            if options.has_key('encoding'):
                lines.append('    :encoding: %s' % options['encoding'])
                del options['encoding']
        else:
            lines = ['::', ''] + ['    %s'%row.rstrip() for row in content.split('\n')]
        lines.append('')
        del options['include-source']
    #kl
#    if options.has_key(
    #kl
#kl    else:
#kl        lines = []

    if num_figs > 0:
        options = ['      :%s: %s' % (key, val) for key, val in
                   options.items()]
        options = "\n".join(options)
        if fname is not None:
            shutil.copyfile(reference, os.path.join(destdir, fname))

        for i in range(num_figs):
            if num_figs == 1:
                outname = basename
            else:
                outname = "%s_%02d" % (basename, i)

            # Copy the linked-to files to the destination within the build tree,
            # and add a link for them
            links = []
            if fname is not None:
                links.append('`source code <%(linkdir)s/%(basename)s.py>`__')
            for format in formats[1:]:
                shutil.copyfile(os.path.join(tmpdir, outname + "." + format),
                                os.path.join(destdir, outname + "." + format))
                links.append('`%s <%s/%s.%s>`__' % (format, linkdir, outname, format))
            links = ', '.join(links) % locals()

            # Output the resulting reST
            lines.extend((template % locals()).split('\n'))
    else:
        lines.extend((exception_template % locals()).split('\n'))

    if len(lines):
        state_machine.insert_input(
            lines, state_machine.input_lines.source(0))

    return []

def mark_plot2_labels(app, document):
    """
    To make plots referenceable, we need to move the reference from
    the "htmlonly" (or "latexonly") node to the actual figure node
    itself.
    """
    for name, explicit in document.nametypes.items():
        if not explicit:
            continue
        labelid = document.nameids[name]
        if labelid is None:
            continue
        node = document.ids[labelid]
        if node.tagname in ('html_only', 'latex_only'):
            for n in node:
                if n.tagname == 'figure':
                    sectname = name
                    for c in n:
                        if c.tagname == 'caption':
                            sectname = c.astext()
                            break

                    node['ids'].remove(labelid)
                    node['names'].remove(name)
                    n['ids'].append(labelid)
                    n['names'].append(name)
                    document.settings.env.labels[name] = \
                        document.settings.env.docname, labelid, sectname
                    break

def setup(app):
    setup.app = app
    setup.config = app.config
    setup.confdir = app.confdir
    print("add directive called")
    app.add_directive('plot2', plot2_directive, True)#, (0, 1, 0))#, **options)
    app.add_config_value(
        'plot2_formats',
        ['png', 'hires.png', 'pdf'],
        True)

    app.connect('doctree-read', mark_plot2_labels)
