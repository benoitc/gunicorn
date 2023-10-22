import os
import subprocess
from xml.etree import ElementTree


def main():
    generate(
        site_path=os.path.join(os.path.dirname(__file__), 'site'),
        special_priorities={'index.html': 1.0})


def generate(site_path, special_priorities, directory_index='index.html'):
    urlset = ElementTree.Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')
    urlset.text = '\n '
    for root, dirs, filenames in os.walk(site_path):
        for filename in filenames:
            if filename.endswith('.html'):
                absolute_filepath = os.path.join(root, filename)
                relative_path = os.path.relpath(absolute_filepath, site_path)
                relative_url = os.path.dirname(relative_path) if filename == directory_index else relative_path
                last_modification = subprocess.check_output(
                    ['git', 'log', '-1', '--pretty="%cI"', absolute_filepath]).decode('ascii').strip('\n"')
                url_element = ElementTree.SubElement(urlset, 'url')
                loc_element = ElementTree.SubElement(url_element, 'loc')
                loc_element.text = 'http://gunicorn.org/' + relative_url
                lastmod_element = ElementTree.SubElement(url_element, 'lastmod')
                lastmod_element.text = last_modification
                priority_element = ElementTree.SubElement(url_element, 'priority')
                priority_element.text = str(special_priorities.get(relative_path, 0.5))
                url_element.tail = priority_element.tail = '\n '
                url_element.text = loc_element.tail = lastmod_element.tail = '\n  '
    # We sort the url nodes instead of the filenames because
    # filenames might be altered by the directory_index option
    urlset[:] = sorted((url for url in urlset), key=lambda url: url[0].text)
    urlset.tail = urlset[-1].tail = '\n'
    with open(os.path.join(site_path, 'sitemap.xml'), 'wb') as sitemap_file:
        ElementTree.ElementTree(urlset).write(sitemap_file, encoding='UTF-8', xml_declaration=True)


if __name__ == '__main__':
    main()
