import { chatMixin }      from './chat.js';
import { pipelineMixin }  from './pipeline.js';
import { domainsMixin }   from './domains.js';
import { campaignsMixin } from './campaigns.js';
import { vaultsMixin }    from './vaults.js';
import { modelsMixin }    from './models.js';
import { documentsMixin } from './documents.js';
import { settingsMixin }  from './settings.js';
import { sidecarMixin }   from './sidecar.js';
import { searchMixin }    from './search.js';

class ChatAPI {
    constructor() {
        this.baseUrl = '';
    }
}

Object.assign(
    ChatAPI.prototype,
    chatMixin,
    pipelineMixin,
    domainsMixin,
    campaignsMixin,
    vaultsMixin,
    modelsMixin,
    documentsMixin,
    settingsMixin,
    sidecarMixin,
    searchMixin,
);

window.chatAPI = new ChatAPI();
