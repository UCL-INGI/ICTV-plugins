from setuptools import setup, find_packages

import ictv.common

setup(
    name='ictv-plugins',
    version=ictv.common.__version__,
    packages=['ictv.plugins.editor', 'ictv.plugins.embed', 'ictv.plugins.img-grabber', 'ictv.plugins.rss'],
    package_dir={'ictv': 'ictv'},
    url='https://github.com/UCL-INGI/ICTV',
    license='GNU AGPL v3',
    author='Michel François, Piraux Maxime, Taffin Ludovic, Nicolas Detienne, Pierre Reinbold',
    author_email='',
    description='ICTV is a simple content management system for digital signage on multiple screens.',
    install_requires=['pyquery', 'BeautifulSoup4', 'feedparser'],
    test_requires=['pytest', 'pytest-xdist', 'pytest-cov', 'paste', 'nose'],
    include_package_data=True,
)