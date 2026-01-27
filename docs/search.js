document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('search-input');
    const resultsDiv = document.getElementById('search-results');
    let searchIndex = [];

    // Load Index
    fetch('search.json')
        .then(response => response.json())
        .then(data => {
            searchIndex = data;
        })
        .catch(err => console.error("Failed to load search index", err));

    searchInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase();
        if (query.length < 2) {
            resultsDiv.classList.add('hidden');
            resultsDiv.innerHTML = '';
            return;
        }

        const results = searchIndex.filter(item => 
            item.title.toLowerCase().includes(query) || 
            item.text.toLowerCase().includes(query)
        ).slice(0, 10); // Limit to 10 results

        displayResults(results);
    });

    function displayResults(results) {
        resultsDiv.innerHTML = '';
        if (results.length === 0) {
            resultsDiv.innerHTML = '<div class="no-results">No results found</div>';
        } else {
            results.forEach(item => {
                const div = document.createElement('div');
                div.className = 'search-result-item';
                div.innerHTML = `<a href="${item.url}">${item.title}</a><span class="search-feed">${item.feed}</span>`;
                resultsDiv.appendChild(div);
            });
        }
        resultsDiv.classList.remove('hidden');
    }
    
    // Close search on click outside
    document.addEventListener('click', (e) => {
        if (!searchInput.contains(e.target) && !resultsDiv.contains(e.target)) {
            resultsDiv.classList.add('hidden');
        }
    });
});
