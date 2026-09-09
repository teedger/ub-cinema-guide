import tengis
import urgoo

t_movie_links = tengis.movie_extract()
t_list = tengis.movie_info(t_movie_links)

u_movie_links = urgoo.movie_extract()
u_list = urgoo.movie_info(u_movie_links)

total_list = t_list + u_list

urgoo.movie_tracker(total_list)
