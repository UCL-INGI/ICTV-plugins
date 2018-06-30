import os

from setuptools import setup

exec(open(os.path.join(os.path.dirname(__file__), 'doc', 'conf.py')).read())

setup(
    name='ictv-plugins',
    version=release,
    packages=['ictv.plugins.editor', 'ictv.plugins.embed', 'ictv.plugins.img-grabber', 'ictv.plugins.rss'],
    package_dir={'ictv': 'ictv'},
    url='https://github.com/UCL-INGI/ICTV-plugins',
    license='GNU AGPL v3',
    author='Michel François, Piraux Maxime, Taffin Ludovic, Nicolas Detienne, Pierre Reinbold',
    author_email='',
    description='ICTV is a simple content management system for digital signage on multiple screens.',
    install_requires=['pyquery', 'BeautifulSoup4', 'feedparser'],
    include_package_data=True,
)
