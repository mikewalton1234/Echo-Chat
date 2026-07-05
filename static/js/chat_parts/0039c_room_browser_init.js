async function initRoomBrowser() {
  if (ROOM_BROWSER.started) return;
  if (!rbHasUI()) return;
  ROOM_BROWSER.started = true;
  rbLoadPersistedRoomBrowserState();

  ROOM_BROWSER.catalog = await rbLoadCatalog();

  try {
    if (!ROOM_BROWSER.selectedCategory || !ROOM_BROWSER.selectedSubcategory) {
      const firstPath = (typeof rbFirstCatalogPath === 'function') ? rbFirstCatalogPath(ROOM_BROWSER.catalog) : null;
      if (firstPath) {
        ROOM_BROWSER.selectedCategory = firstPath.category;
        ROOM_BROWSER.selectedSubcategory = firstPath.subcategory;
      }
    }
  } catch {}

  rbRenderCategoryTree();
  await rbRefreshLists();

  $('btnOpenCreateRoom')?.addEventListener('click', rbOpenCreateRoomModal);
  $('btnCloseCreateRoom')?.addEventListener('click', () => rbCloseModal('createRoomModal'));
  $('btnCancelCreateRoom')?.addEventListener('click', () => rbCloseModal('createRoomModal'));
  $('btnCreateRoom')?.addEventListener('click', rbCreateRoom);
  $('crName')?.addEventListener('input', crUpdateNameCount);
  $('crName')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); rbCreateRoom(); }
  });
  document.querySelectorAll('input[name="crVis"]').forEach((radio) => {
    radio.addEventListener('change', crUpdateVisibilityCards);
  });
  $('crNSFW')?.addEventListener('change', () => {
    const cr18 = $('cr18');
    if ($('crNSFW')?.checked && cr18) cr18.checked = true;
  });

  $('btnCloseInviteRoom')?.addEventListener('click', () => rbCloseModal('inviteRoomModal'));
  $('btnInviteRoom')?.addEventListener('click', rbSendInvite);
  $('irUser')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); rbSendInvite(); }
  });

  const catSearch = $('rbCatSearch');
  if (catSearch) {
    catSearch.value = ROOM_BROWSER.catQuery || '';
    const renderCategorySearch = (typeof ecRafThrottle === 'function') ? ecRafThrottle(() => rbRenderCategoryTree()) : rbRenderCategoryTree;
    catSearch.addEventListener('input', () => {
      ROOM_BROWSER.catQuery = catSearch.value || '';
      renderCategorySearch();
    });
  }

  const roomSearch = $('rbRoomSearch');
  if (roomSearch) {
    roomSearch.value = ROOM_BROWSER.roomQuery || '';
    const renderRoomSearch = (typeof ecRafThrottle === 'function') ? ecRafThrottle(() => {
      rbRenderRoomLists();
      rbUpdateCountsInDom();
    }) : () => { rbRenderRoomLists(); rbUpdateCountsInDom(); };
    roomSearch.addEventListener('input', () => {
      ROOM_BROWSER.roomQuery = roomSearch.value || '';
      renderRoomSearch();
    });
  }

  const roomSort = $('rbRoomSort');
  if (roomSort) {
    roomSort.value = ROOM_BROWSER.roomsSort || 'active';
    roomSort.addEventListener('change', () => {
      ROOM_BROWSER.roomsSort = roomSort.value || 'active';
      rbRenderRoomLists();
      rbUpdateCountsInDom();
    });
  }

  const hideEmpty = $('rbHideEmpty');
  if (hideEmpty) {
    hideEmpty.checked = !!ROOM_BROWSER.hideEmpty;
    hideEmpty.addEventListener('change', () => {
      ROOM_BROWSER.hideEmpty = !!hideEmpty.checked;
      rbRenderRoomLists();
      rbUpdateCountsInDom();
    });
  }

  const roomStatus = $('rbRoomStatusFilter');
  if (roomStatus) {
    roomStatus.value = ROOM_BROWSER.roomStatusFilter || 'all';
    roomStatus.addEventListener('change', () => {
      ROOM_BROWSER.roomStatusFilter = roomStatus.value || 'all';
      rbRenderRoomLists();
      rbUpdateCountsInDom();
    });
  }


  const customSearch = $('rbCustomSearch');
  if (customSearch) {
    customSearch.value = ROOM_BROWSER.customQuery || '';
    const renderCustomSearch = (typeof ecRafThrottle === 'function') ? ecRafThrottle(() => {
      rbRenderRoomLists();
      rbUpdateCountsInDom();
    }) : () => { rbRenderRoomLists(); rbUpdateCountsInDom(); };
    customSearch.addEventListener('input', () => {
      ROOM_BROWSER.customQuery = customSearch.value || '';
      renderCustomSearch();
    });
  }

  const customFilter = $('rbCustomFilter');
  if (customFilter) {
    customFilter.value = ROOM_BROWSER.customFilter || 'all';
    customFilter.addEventListener('change', () => {
      ROOM_BROWSER.customFilter = customFilter.value || 'all';
      rbRenderRoomLists();
      rbUpdateCountsInDom();
    });
  }

  const customSort = $('rbCustomSort');
  if (customSort) {
    customSort.value = ROOM_BROWSER.customSort || 'active';
    customSort.addEventListener('change', () => {
      ROOM_BROWSER.customSort = customSort.value || 'active';
      rbRenderRoomLists();
      rbUpdateCountsInDom();
    });
  }

  document.querySelectorAll('#rbScopeBar .rbScopeChip').forEach((btn) => {
    btn.addEventListener('click', async () => {
      ROOM_BROWSER.roomScope = String(btn.dataset.rbScope || 'all');
      try {
        if (typeof window.ecSetMobileRoomBrowserStep === 'function') {
          window.ecSetMobileRoomBrowserStep(ROOM_BROWSER.roomScope === 'custom' ? 'custom' : 'official');
        }
      } catch {}
      rbRenderRoomLists();
      if (['all', 'official', 'custom'].includes(ROOM_BROWSER.roomScope)) {
        await rbRefreshLists();
      }
    });
  });

  if (!ROOM_BROWSER._customExpiryTimer) {
    ROOM_BROWSER._customExpiryTimer = setInterval(() => {
      if (typeof rbUpdateCustomRoomCountdowns === 'function') rbUpdateCustomRoomCountdowns();
    }, 1000);
  }
  rbStartPolling();
}
