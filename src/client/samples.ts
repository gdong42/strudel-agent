import type { SampleListPayload } from './bridge';

export class SampleListView {
  constructor(private readonly element: HTMLElement) {}

  render(catalog: SampleListPayload, loadError = false): void {
    this.element.replaceChildren();
    this.element.append(this.libraryStatus(catalog, loadError));
    if (!catalog.configured) {
      return;
    }
    if (catalog.samples.length === 0) {
      return;
    }

    for (const sample of catalog.samples) {
      const item = document.createElement('div');
      item.className = 'sample-item';

      const header = document.createElement('div');
      header.className = 'sample-header';
      const name = document.createElement('code');
      name.textContent = sample.name;
      header.append(name);

      if (sample.tags.length > 0) {
        const tags = document.createElement('div');
        tags.className = 'sample-tags';
        for (const tag of sample.tags) {
          const tagElement = document.createElement('span');
          tagElement.className = 'sample-tag';
          tagElement.textContent = tag;
          tags.append(tagElement);
        }
        header.append(tags);
      }

      item.append(header);
      if (sample.description) {
        const description = document.createElement('p');
        description.textContent = sample.description;
        item.append(description);
      }
      this.element.append(item);
    }
  }

  renderUnavailable(): void {
    this.element.replaceChildren();
    this.element.textContent = 'Sample catalog unavailable.';
  }

  private libraryStatus(catalog: SampleListPayload, loadError: boolean): HTMLElement {
    const status = document.createElement('p');
    status.className = `sample-library-status${loadError ? ' sample-library-error' : ''}`;
    if (loadError) {
      status.textContent = 'Local samples failed to load.';
    } else if (catalog.library.fileCount > 0) {
      const soundUnit = catalog.library.soundCount === 1 ? 'sound' : 'sounds';
      const fileUnit = catalog.library.fileCount === 1 ? 'file' : 'files';
      status.textContent = `${catalog.library.soundCount} local ${soundUnit} · ${catalog.library.fileCount} ${fileUnit}`;
    } else if (catalog.library.configured) {
      status.textContent = 'Local sample library is empty.';
    } else if (catalog.configured) {
      status.textContent = 'Declared samples only.';
    } else {
      status.textContent = 'No custom samples.';
    }
    return status;
  }
}
