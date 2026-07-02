// Search API methods
export const searchMixin = {
    async textSearchByDomain(domainId, queryText, limit = 20) {
        const response = await fetch(`${this.baseUrl}/api/db/search/domain`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                domain_id: domainId,
                query_text: queryText,
                limit,
            }),
        });
        if (!response.ok) {
            let errMsg = response.statusText;
            try {
                const errData = await response.json();
                errMsg = errData.detail || errData.message || errMsg;
            } catch (_) {}
            throw new Error(`Text search failed: ${errMsg}`);
        }
        return response.json();
    },
};
