import QtQuick
import QtQuick.Layouts
import "../theme"

// "101–150 of 987 · 50 / page · ‹ Page 3 / 20 ›" (same as the web Pager). Bind it to a PagedStore:
//   Pager { store: Cameras; sizes: [25, 50, 100] }
// or drive it by hand with page / pageSize / total and the `paged(page)` signal (in-memory lists).
// Hidden when everything fits on one page and the page size cannot be changed.
RowLayout {
    id: root

    property var store: null
    property int page: store ? store.page : 1
    property int pageSize: store ? store.pageSize : 50
    property int total: store ? store.total : 0
    property var sizes: []  // e.g. [25, 50, 100]: shows the rows-per-page select
    signal paged(int page)

    readonly property int pageCount: Math.max(1, Math.ceil(Math.max(0, total) / pageSize))
    readonly property int current: Math.min(Math.max(1, page), pageCount)
    readonly property string label: {
        if (total <= 0)
            return "0 of 0"
        const first = (current - 1) * pageSize + 1
        return first + "–" + Math.min(total, first + pageSize - 1) + " of " + total
    }

    function go(p) {
        if (store)
            store.setPage(p)
        else
            paged(p)
    }

    visible: pageCount > 1 || (sizes.length > 0 && total > Math.min(...sizes))
    spacing: 6

    AppText { text: root.label; variant: "small" }
    Item { Layout.fillWidth: true }
    AppSelect {
        visible: root.sizes.length > 0 && root.store !== null
        implicitWidth: 132
        implicitHeight: 30
        options: root.sizes.map(s => ({ value: s, label: s + " / page" }))
        value: root.pageSize
        onPicked: v => root.store.setPageSize(v)
    }
    AppButton {
        objectName: "pagerPrev"
        variant: "ghost"; size: "icon"; iconName: "chevron-left"; tip: "Previous page"
        implicitHeight: 30
        enabled: root.current > 1
        onClicked: root.go(root.current - 1)
    }
    AppText {
        text: "Page " + root.current + " / " + root.pageCount
        variant: "small"
        horizontalAlignment: Text.AlignHCenter
        Layout.minimumWidth: 78
    }
    AppButton {
        objectName: "pagerNext"
        variant: "ghost"; size: "icon"; iconName: "chevron-right"; tip: "Next page"
        implicitHeight: 30
        enabled: root.current < root.pageCount
        onClicked: root.go(root.current + 1)
    }
}
