$(document).ready(function() {
  Tabs.init();
});

var Tabs = {
    init: function(){
        var activateTab = function ($tab) {
            var // this links tabs set
                $tabs = $tab.parents('.tabs'),
                // currently active tab
                activeTab = {
                    'tab' : $tabs.find('ul').children('li.active'),
                    'content' : $tabs.find('div[data-tab].active')
                },
                // newly clicked tab
                newTab = {
                    'tab' : $tab.parent('li'),
                    'content' : $tabs.find('[data-tab=' + $tab.attr('href').replace('#', '') + ']')
                },
                x, y;

            // remove active class from tab and content
            for (x in activeTab) {
                activeTab[x].removeClass('active');
            }

            // add active class to tab and content
            for (y in newTab) {
                newTab[y].addClass('active');
            }
        };
        // hook up tab links
        $(document).on('click', '.tabs ul li a', function(e) {
            activateTab($(this));
            //alert($(this));
        });

        // hook up initial load active tab
        if (window.location.hash) {
            var $activeTab = $('a[href="'  +  window.location.hash  +  '"]');
            if ($activeTab.length && $activeTab.parents('.tabs').length) {
                activateTab($activeTab);
            }
        }
    }
};